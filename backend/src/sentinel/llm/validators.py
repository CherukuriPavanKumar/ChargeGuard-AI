"""The rebuttal draft schema and its hallucination guard.

A language model writing a legal-adjacent document for submission to a card
issuer has exactly one catastrophic failure mode: **citing evidence that does
not exist**.  A fluent, confident representment referencing "the signed delivery
receipt dated 14 March" when no such receipt is in the bundle is worse than no
filing at all -- it is a false statement submitted to a financial institution,
and if the issuer checks, the merchant's credibility on every future dispute is
damaged.

This module is the guard.  Every artifact the model may reference is enumerated
from the bundle *before* generation, the model is told to cite only from that
list, and :func:`validate_draft` rejects the whole draft if it cites anything
outside it.  Rejection is total rather than partial: a model that invented one
citation cannot be trusted to have grounded the surrounding prose, so we discard
the draft and fall back to the deterministic template.

Note what is *not* validated: the prose itself.  We cannot verify that a
paragraph is persuasive, and pretending to would be theatre.  What we can verify
mechanically is that every artifact reference resolves to something we hold, and
that is what we do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinel.schemas.evidence import EvidenceBundle, ExtractionStatus

#: Maximum characters accepted in any single narrative field. A model that runs
#: away produces an unusable document and burns tokens; this bounds both.
MAX_FIELD_CHARS: int = 2400

#: Phrases that must never appear in a representment. The first group is
#: hedging that undermines the filing; the second is leakage of internal
#: decision state that the model should never have seen in the first place and
#: must certainly not print in a document sent to an issuer.
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "as an ai",
    "language model",
    "i cannot",
    "i'm unable",
    "win probability",
    "expected value",
    "threshold",
    "our model",
    "confidence score",
    "policy gate",
)


class RebuttalDraft(BaseModel):
    """The structured output contract for rebuttal synthesis.

    Deliberately narrow.  The model does not get to choose the document
    structure, the section order, or which sections exist -- it fills four named
    slots, and :mod:`sentinel.packet.renderer` decides how they are presented.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: str = Field(
        ...,
        min_length=40,
        max_length=MAX_FIELD_CHARS,
        description=(
            "One paragraph stating what the merchant sold, to whom, and why the "
            "chargeback should be reversed. Written for an issuer analyst who "
            "will spend under two minutes on it."
        ),
    )
    evidence_narrative: str = Field(
        ...,
        min_length=40,
        max_length=MAX_FIELD_CHARS,
        description=(
            "Prose walkthrough of the artifacts in the order a reviewer should "
            "consider them, each reference resolving to a real bundle artifact."
        ),
    )
    scheme_argument: str = Field(
        ...,
        min_length=40,
        max_length=MAX_FIELD_CHARS,
        description=(
            "Reason-code-specific argument citing the applicable scheme rule and "
            "the compelling-evidence standard it sets."
        ),
    )
    cited_artifacts: tuple[str, ...] = Field(
        default=(),
        description=(
            "Artifact identifiers referenced above. Validated against the "
            "bundle's own index; anything outside it rejects the draft."
        ),
    )

    @field_validator("summary", "evidence_narrative", "scheme_argument")
    @classmethod
    def _reject_forbidden_phrases(cls, value: str) -> str:
        """Reject drafts containing assistant-voice or internal-state leakage."""
        lowered = value.lower()
        for phrase in FORBIDDEN_PHRASES:
            if phrase in lowered:
                raise ValueError(
                    f"draft contains forbidden phrase {phrase!r}; a representment "
                    f"must not hedge or expose internal decision state"
                )
        return value.strip()

    @field_validator("cited_artifacts", mode="before")
    @classmethod
    def _coerce_citations(cls, value: object) -> object:
        """Accept a list or tuple, normalising each entry to a stripped string."""
        if value is None:
            return ()
        if isinstance(value, (list, tuple)):
            return tuple(str(item).strip() for item in value if str(item).strip())
        return value


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """Result of checking a draft against a bundle."""

    ok: bool
    """True when the draft may be used."""

    reason: str
    """Empty when ``ok``; otherwise why the draft was rejected."""

    unknown_citations: tuple[str, ...] = ()
    """Artifact identifiers cited but not present in the bundle."""


def artifact_index(bundle: EvidenceBundle) -> tuple[str, ...]:
    """Enumerate every artifact identifier this bundle actually contains.

    This is both the whitelist handed to the model and the set
    :func:`validate_draft` checks against, so the two cannot drift.

    Identifiers are stable, human-readable, and reason-code agnostic. They
    appear verbatim in the rendered packet's artifact index, so an issuer
    analyst reading a citation can find the corresponding exhibit.
    """
    artifacts: list[str] = [
        f"ORDER_RECORD_{bundle.order.order_id}",
        "AUTHORISATION_AVS_RESULT",
        "AUTHORISATION_CVV_RESULT",
        "AUTHORISATION_3DS_RESULT",
        f"SESSION_LOG_{bundle.session.device_fingerprint[:16]}",
    ]

    pod = bundle.pod
    if pod.extraction_status is not ExtractionStatus.ABSENT:
        artifacts.append(
            f"POD_SLIP_{pod.awb_number}" if pod.awb_number else "POD_SLIP"
        )
        if pod.signature_captured:
            artifacts.append("POD_DELIVERY_SIGNATURE")
        if pod.scan_count > 0:
            artifacts.append("CARRIER_SCAN_TRAIL")
        if pod.delivered_at is not None:
            artifacts.append("POD_DELIVERY_TIMESTAMP")

    if bundle.merchant_comms_count > 0:
        artifacts.append("MERCHANT_CUSTOMER_COMMS_LOG")
    if bundle.refund_requested:
        artifacts.append("REFUND_LEDGER_ENTRY")
    if bundle.prior_dispute_count > 0:
        artifacts.append("CARDHOLDER_DISPUTE_HISTORY")

    return tuple(artifacts)


#: Matches an ALL_CAPS artifact-style token inside prose, so we can catch a model
#: that invents a citation in the narrative without listing it in the array.
#:
#: The trailing ``(?!\.\d)`` is load-bearing. Without it the pattern matches
#: ``VISA_13`` out of the reason code ``VISA_13.1`` and flags a merchant's own
#: scheme citation as a fabricated artifact -- which rejected every Visa-coded
#: draft while leaving Mastercard ones alone, because ``MC`` is two characters
#: and fails the ``{2,}`` quantifier. A guard that fires on correct output is
#: worse than no guard: it trains the operator to route around it.
_INLINE_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+\b(?!\.\d)")


def _schema_vocabulary() -> frozenset[str]:
    """ALL_CAPS tokens that belong to the schema, not to the artifact index.

    Status and enum values legitimately appear in a narrative -- a draft may say
    the authentication result was ``NOT_ENROLLED``. Those are facts about the
    bundle, not references to exhibits, and must not trip the guard.

    Derived from the enums themselves rather than hand-listed, so a new status
    value cannot silently start causing false rejections.
    """
    from sentinel.schemas.dispute import CardNetwork, ReasonCode
    from sentinel.schemas.evidence import Carrier, ThreeDSStatus

    tokens: set[str] = set()
    for enum_cls in (ReasonCode, ThreeDSStatus, ExtractionStatus, Carrier, CardNetwork):
        for member in enum_cls:
            value = str(member.value)
            tokens.add(value)
            # A reason code like "VISA_13.1" can also surface truncated at the
            # decimal point by the tokeniser; admit that prefix too.
            tokens.add(value.split(".")[0])
    return frozenset(tokens)


#: Resolved once at import; the enums are closed vocabularies and never change
#: at runtime.
SCHEMA_VOCABULARY: frozenset[str] = _schema_vocabulary()


def validate_draft(
    draft: RebuttalDraft, bundle: EvidenceBundle
) -> ValidationOutcome:
    """Check every citation in ``draft`` against the bundle's artifact index.

    Two checks, because a model can hallucinate in two places:

    1. Entries in ``cited_artifacts`` that are not in the index.
    2. Artifact-shaped tokens appearing in the prose that are not in the index --
       a model that writes "per POD_SIGNED_RECEIPT_9931" while listing only real
       artifacts in the array has still put a false reference in the document
       the issuer reads.

    Returns:
        A :class:`ValidationOutcome`. ``ok=False`` means the caller must fall
        back to the deterministic template.
    """
    available = set(artifact_index(bundle))

    unknown = tuple(
        citation for citation in draft.cited_artifacts if citation not in available
    )
    if unknown:
        return ValidationOutcome(
            ok=False,
            reason=(
                f"draft cites {len(unknown)} artifact(s) absent from the bundle: "
                f"{', '.join(unknown)}"
            ),
            unknown_citations=unknown,
        )

    prose = " ".join(
        (draft.summary, draft.evidence_narrative, draft.scheme_argument)
    )
    inline_unknown = tuple(
        token
        for token in set(_INLINE_TOKEN.findall(prose))
        if token not in available and token not in SCHEMA_VOCABULARY
    )
    if inline_unknown:
        return ValidationOutcome(
            ok=False,
            reason=(
                "draft references artifact-shaped identifiers in prose that are "
                f"not in the bundle: {', '.join(sorted(inline_unknown))}"
            ),
            unknown_citations=inline_unknown,
        )

    if not draft.cited_artifacts:
        return ValidationOutcome(
            ok=False,
            reason="draft cites no artifacts; a representment with no exhibits "
            "is not a filing",
        )

    return ValidationOutcome(ok=True, reason="")
