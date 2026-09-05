"""Constrained rebuttal synthesis.

What the model is allowed to do
===============================
Write four paragraphs of prose, citing from a fixed whitelist.

What the model is **not** allowed to do
=======================================
Influence any decision.  Look closely at :func:`synthesise`: its parameters are
``(dispute, bundle, settings)``.  There is no ``p_win`` parameter, no
``threshold`` parameter, and no ``Decision`` parameter, because the model must
not receive them -- not for context, not for tone-setting, not for anything.
This is enforced by the signature itself rather than by a convention, so a
future caller cannot pass them by accident.

The direction of information flow is strictly one way::

    features -> model -> p_win -> policy engine -> Decision
                                                      |
                                                      v
                                          (CONTEST only) packet job
                                                      |
                                                      v
                              dispute + bundle -> LLM -> prose -> PDF

Synthesis happens *downstream* of the decision and only when the decision was
CONTEST.  There is no edge from the prose back to the decision, and there is no
module in which one could be added without violating INVARIANT 1.

Failure policy
==============
Four failure modes, all handled, none propagating:

======================================  ==================================
failure                                  response
======================================  ==================================
no API key configured                    template, immediately, no attempt
any API exception (network, auth, rate)  template, immediately
malformed or unparseable output          retry once, then template
draft cites a non-existent artifact      retry once, then template
======================================  ==================================

Exactly one retry.  A model that produced unparseable JSON once will often
succeed on a second pass; one that fails twice is not going to succeed on a
third, and the packet job has a deadline.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from sentinel.config import Settings, get_settings
from sentinel.llm import templates
from sentinel.llm.validators import (
    RebuttalDraft,
    artifact_index,
    validate_draft,
)
from sentinel.schemas.decision import PacketSource
from sentinel.schemas.dispute import DisputeEvent
from sentinel.schemas.evidence import EvidenceBundle, ExtractionStatus

logger = logging.getLogger(__name__)

#: Location of the system prompt, kept as a text file so it is reviewable in a
#: diff rather than buried in a string literal.
PROMPT_PATH: Path = Path(__file__).parent / "prompts" / "rebuttal_system.txt"

#: Attempts before giving up and falling back to the template.
MAX_ATTEMPTS: int = 2

#: Matches a JSON object inside a response that wrapped it in prose or fences.
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """A draft plus the provenance of how it was produced.

    ``source`` and ``fallback_reason`` are surfaced in the API response and in
    the rendered packet footer.  A merchant reviewing a filing is entitled to
    know whether the prose was model-written or templated, and if the model was
    skipped, why.
    """

    draft: RebuttalDraft
    source: PacketSource
    attempts: int
    fallback_reason: str = ""

    @property
    def used_llm(self) -> bool:
        """True when the returned draft came from the language model."""
        return self.source is PacketSource.LLM


def load_system_prompt() -> str:
    """Read the system prompt from disk.

    Falls back to a compact inline prompt if the file is missing, so a broken
    packaging step degrades the output quality rather than breaking the job.
    """
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("system prompt unreadable at %s: %s", PROMPT_PATH, exc)
        return (
            "You draft chargeback representment arguments for an Indian "
            "e-commerce merchant. Return a single JSON object with keys "
            "summary, evidence_narrative, scheme_argument and cited_artifacts. "
            "Cite only artifact identifiers from the supplied index. Never "
            "assert a fact absent from the input. Never mention probabilities, "
            "scores, thresholds or automated systems."
        )


def build_user_message(dispute: DisputeEvent, bundle: EvidenceBundle) -> str:
    """Serialise the dispute and bundle into the model's input.

    Note what this function does **not** include: no win probability, no
    threshold, no decision, no model version, no feature values.  The model sees
    the same facts a human paralegal would be handed and nothing about how the
    system evaluated them.
    """
    pod = bundle.pod
    order = bundle.order
    session = bundle.session

    if pod.extraction_status is ExtractionStatus.ABSENT:
        pod_block = "PROOF OF DELIVERY: none held."
    else:
        pod_block = "\n".join(
            (
                "PROOF OF DELIVERY",
                f"  extraction status : {pod.extraction_status}",
                f"  carrier           : {pod.carrier}",
                f"  waybill           : {pod.awb_number or '(not legible)'}",
                f"  delivered at      : "
                f"{pod.delivered_at.isoformat() if pod.delivered_at else '(not legible)'}",
                f"  signed by         : {pod.recipient_name or '(not legible)'}",
                f"  signature captured: {pod.signature_captured}",
                f"  delivery address  : {pod.delivery_address or '(not legible)'}",
                f"  carrier scans     : {pod.scan_count}",
            )
        )

    return "\n".join(
        (
            "DISPUTE",
            f"  dispute id     : {dispute.dispute_id}",
            f"  transaction id : {dispute.transaction_id}",
            f"  reason code    : {dispute.reason_code}",
            f"  network        : {dispute.network}",
            f"  amount         : INR {dispute.amount_inr:,.2f}",
            f"  raised at      : {dispute.disputed_at.isoformat()}",
            "",
            "ORDER",
            f"  order id         : {order.order_id}",
            f"  customer         : {order.customer_name}",
            f"  placed at        : {order.placed_at.isoformat()}",
            f"  items            : {', '.join(order.items) if order.items else '(none recorded)'}",
            f"  order total      : INR {order.order_total:,.2f}",
            f"  billing address  : {order.billing_address}",
            f"  shipping address : {order.shipping_address}",
            f"  AVS match        : {order.avs_match}",
            f"  CVV match        : {order.cvv_match}",
            f"  3-D Secure       : {order.three_ds_status}",
            "",
            pod_block,
            "",
            "SESSION",
            f"  ip address          : {session.ip_address}",
            f"  device fingerprint  : {session.device_fingerprint}",
            f"  user agent          : {session.user_agent}",
            f"  login at            : {session.login_at.isoformat()}",
            f"  account created at  : {session.account_created_at.isoformat()}",
            "",
            "HISTORY",
            f"  prior disputes by this cardholder : {bundle.prior_dispute_count}",
            f"  refund requested or issued        : {bundle.refund_requested}",
            f"  merchant communications logged    : {bundle.merchant_comms_count}",
            "",
            "ARTIFACT INDEX -- you may cite these identifiers and no others:",
            *(f"  {identifier}" for identifier in artifact_index(bundle)),
        )
    )


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response.

    Tolerant of the two things models actually do wrong: wrapping the object in
    a markdown fence, and prefacing it with a sentence.

    Raises:
        ValueError: when no parseable object is present.
    """
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK.search(stripped)
    if match is None:
        raise ValueError("no JSON object found in model response")

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"model response contained malformed JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("model response JSON was not an object")
    return parsed


def _call_anthropic(
    system_prompt: str, user_message: str, settings: Settings
) -> str:
    """Make one call to the Anthropic API and return the text content.

    Raises:
        RuntimeError: on any failure. The caller converts this to a fallback;
            it never escapes :func:`synthesise`.
    """
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(f"anthropic SDK not installed: {exc}") from exc

    try:
        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=settings.llm_timeout_s,
        )
        response = client.messages.create(
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        # Deliberately broad: auth errors, rate limits, timeouts, connection
        # resets and SDK-internal errors all mean the same thing to the packet
        # job, which is that it must produce a document without the model.
        raise RuntimeError(f"{type(exc).__name__}: {exc}") from exc

    chunks: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            chunks.append(text)

    if not chunks:
        raise RuntimeError("model returned no text content")
    return "".join(chunks)


def synthesise(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    settings: Settings | None = None,
) -> SynthesisResult:
    """Produce a validated rebuttal draft.

    **Never raises.**  Always returns a usable draft, from the model where
    possible and from the deterministic template otherwise.

    Note the parameters: there is no ``p_win``, no ``threshold`` and no
    ``Decision``.  The synthesiser is structurally incapable of seeing the
    decision it is writing for.

    Args:
        dispute: The chargeback being rebutted.
        bundle: The evidence held for it.
        settings: Configuration; the process singleton when omitted.

    Returns:
        A :class:`SynthesisResult` carrying the draft and its provenance.
    """
    cfg = settings if settings is not None else get_settings()

    if not cfg.anthropic_api_key:
        return SynthesisResult(
            draft=templates.render_template(dispute, bundle),
            source=PacketSource.TEMPLATE,
            attempts=0,
            fallback_reason="no ANTHROPIC_API_KEY configured",
        )

    system_prompt = load_system_prompt()
    user_message = build_user_message(dispute, bundle)
    last_reason = "unknown"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = _call_anthropic(system_prompt, user_message, cfg)
        except RuntimeError as exc:
            # An API-level failure will not be fixed by retrying with identical
            # input inside the same job, so stop immediately.
            logger.warning("LLM call failed on attempt %d: %s", attempt, exc)
            last_reason = f"API error: {exc}"
            break

        try:
            payload = _extract_json(raw)
            draft = RebuttalDraft.model_validate(payload)
        except (ValueError, ValidationError) as exc:
            logger.warning("LLM output rejected on attempt %d: %s", attempt, exc)
            last_reason = f"schema validation failed: {exc}"
            continue

        outcome = validate_draft(draft, bundle)
        if not outcome.ok:
            logger.warning(
                "LLM draft failed the hallucination guard on attempt %d: %s",
                attempt,
                outcome.reason,
            )
            last_reason = f"hallucination guard: {outcome.reason}"
            continue

        return SynthesisResult(
            draft=draft, source=PacketSource.LLM, attempts=attempt
        )

    return SynthesisResult(
        draft=templates.render_template(dispute, bundle),
        source=PacketSource.TEMPLATE,
        attempts=MAX_ATTEMPTS,
        fallback_reason=last_reason,
    )


def llm_available(settings: Settings | None = None) -> bool:
    """True when an API key is configured and the SDK is importable.

    Used by ``/health`` to report degraded capability honestly rather than
    claiming full function and templating every packet.
    """
    cfg = settings if settings is not None else get_settings()
    if not cfg.anthropic_api_key:
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True
