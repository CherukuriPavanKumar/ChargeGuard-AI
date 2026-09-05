"""Representment document rendering.

Jinja2 to HTML always; WeasyPrint to PDF where the engine is installable.

Why the PDF is optional
=======================
WeasyPrint depends on a native GTK/Pango/Cairo stack that is straightforward on
Linux, awkward on macOS, and genuinely painful on Windows.  Making the packet
endpoint hard-depend on it would mean the demo fails to produce a document on
the most common judging environment, which is a worse outcome than producing an
HTML document.

So the renderer produces HTML unconditionally and attempts the PDF, reporting
honestly which it managed.  :class:`~sentinel.schemas.decision.EvidencePacket`
carries ``pdf_path: str | None`` for exactly this reason -- the schema admits
the degraded case rather than lying about it.

Where this sits in the pipeline
===============================
**Downstream of the decision, and only on CONTEST.**  Packet rendering is a
background job behind ``POST /v1/disputes/{id}/packet``, deliberately off the
synchronous scoring path: it involves an LLM call and a native PDF engine, and
neither belongs inside a 200 ms budget.  Nothing this module produces can reach
the policy engine.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sentinel.config import Settings, get_settings
from sentinel.llm.synthesiser import SynthesisResult, synthesise
from sentinel.llm.validators import RebuttalDraft, artifact_index
from sentinel.schemas.decision import EvidencePacket, PacketSource
from sentinel.schemas.dispute import DisputeEvent
from sentinel.schemas.evidence import EvidenceBundle, ExtractionStatus

logger = logging.getLogger(__name__)

#: Directory holding the Jinja templates.
TEMPLATE_DIR: Path = Path(__file__).parent / "templates"

#: Human-readable descriptions for each artifact identifier, shown in the packet
#: index so an issuer analyst knows what a citation refers to. Prefix-matched so
#: identifiers carrying an embedded id (order number, waybill) still resolve.
ARTIFACT_DESCRIPTIONS: tuple[tuple[str, str], ...] = (
    ("ORDER_RECORD_", "Merchant order record: line items, totals, addresses."),
    ("AUTHORISATION_AVS_RESULT",
     "Address Verification Service result returned at authorisation."),
    ("AUTHORISATION_CVV_RESULT",
     "CVV2/CVC2 verification result returned at authorisation."),
    ("AUTHORISATION_3DS_RESULT",
     "3-D Secure authentication outcome and liability position."),
    ("SESSION_LOG_",
     "Checkout session telemetry: IP, device fingerprint, timestamps."),
    ("POD_SLIP_", "Carrier proof-of-delivery slip as received and parsed."),
    ("POD_SLIP", "Carrier proof-of-delivery slip as received and parsed."),
    ("POD_DELIVERY_SIGNATURE",
     "Signature captured by the carrier at the point of handover."),
    ("POD_DELIVERY_TIMESTAMP",
     "Delivery timestamp recorded on the carrier slip."),
    ("CARRIER_SCAN_TRAIL",
     "Carrier network scan events tracking the consignment."),
    ("MERCHANT_CUSTOMER_COMMS_LOG",
     "Logged merchant-to-cardholder communications for this order."),
    ("REFUND_LEDGER_ENTRY",
     "Merchant refund ledger entry against this transaction."),
    ("CARDHOLDER_DISPUTE_HISTORY",
     "Prior disputes raised by this cardholder against this merchant."),
)


def _describe_artifact(identifier: str) -> str:
    """Return a human-readable description for an artifact identifier."""
    for prefix, description in ARTIFACT_DESCRIPTIONS:
        if identifier.startswith(prefix):
            return description
    return "Supporting record held by the merchant."


def _build_environment() -> Environment:
    """Construct the Jinja environment with autoescaping on.

    Autoescaping matters here specifically: the narrative is model-generated
    text and the artifact identifiers derive from OCR output, so both are
    untrusted with respect to markup. Escaping is on by default rather than
    remembered per-template.
    """
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_html(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    draft: RebuttalDraft,
    source: PacketSource,
    fallback_reason: str = "",
    generated_at: datetime | None = None,
) -> str:
    """Render the representment document to HTML.

    The artifact index lists **everything the bundle holds**, marking which
    entries the narrative actually cited. Showing the uncited ones is
    deliberate: an issuer analyst can see the full evidentiary position rather
    than only the parts the narrative chose to lean on.
    """
    cited = set(draft.cited_artifacts)
    artifacts = [
        {
            "identifier": identifier,
            "description": _describe_artifact(identifier),
            "cited": identifier in cited,
        }
        for identifier in artifact_index(bundle)
    ]

    template = _build_environment().get_template("rebuttal.html")
    return template.render(
        dispute=dispute,
        bundle=bundle,
        draft=draft,
        artifacts=artifacts,
        source=source.value,
        fallback_reason=fallback_reason,
        generated_at=generated_at or datetime.now(timezone.utc),
    )


def render_pdf(html: str, out_path: Path) -> Path | None:
    """Render HTML to PDF via WeasyPrint. Returns None if unavailable.

    Never raises. A missing native stack, a font-config failure, or an
    unwritable path all return None, and the caller ships the HTML.
    """
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except Exception as exc:
        logger.info(
            "PDF rendering unavailable (%s: %s); HTML output only",
            type(exc).__name__,
            exc,
        )
        return None

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        HTML(string=html).write_pdf(str(out_path))
    except Exception as exc:
        logger.warning("PDF rendering failed: %s: %s", type(exc).__name__, exc)
        return None

    return out_path


def build_packet(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    settings: Settings | None = None,
    write_to_disk: bool = True,
) -> EvidencePacket:
    """Synthesise, validate, and render a complete representment packet.

    **Never raises.**  LLM unavailable, LLM hallucinating, PDF engine missing --
    all produce a valid packet.

    Note the signature: no ``Decision`` parameter.  The packet builder cannot see
    the decision it is documenting, which is what makes it structurally
    impossible for the narrative to be conditioned on the action taken.

    Args:
        dispute: The chargeback being rebutted.
        bundle: The evidence held for it.
        settings: Configuration; the process singleton when omitted.
        write_to_disk: When False, render in memory only and leave
            ``pdf_path`` as None. Used by tests and by the preview endpoint.

    Returns:
        A fully populated :class:`EvidencePacket`.
    """
    cfg = settings if settings is not None else get_settings()
    generated_at = datetime.now(timezone.utc)

    result: SynthesisResult = synthesise(dispute, bundle, cfg)

    html = render_html(
        dispute=dispute,
        bundle=bundle,
        draft=result.draft,
        source=result.source,
        fallback_reason=result.fallback_reason,
        generated_at=generated_at,
    )

    pdf_path: Path | None = None
    if write_to_disk:
        cfg.ensure_dirs()
        html_path = cfg.packets_dir / f"{dispute.dispute_id}.html"
        try:
            html_path.write_text(html, encoding="utf-8")
        except OSError as exc:
            logger.warning("could not write packet HTML: %s", exc)
        pdf_path = render_pdf(html, cfg.packets_dir / f"{dispute.dispute_id}.pdf")

    return EvidencePacket(
        dispute_id=dispute.dispute_id,
        reason_code=dispute.reason_code.value,
        summary=result.draft.summary,
        evidence_narrative=result.draft.evidence_narrative,
        scheme_argument=result.draft.scheme_argument,
        cited_artifacts=result.draft.cited_artifacts,
        source=result.source,
        html=html,
        pdf_path=str(pdf_path) if pdf_path is not None else None,
        generated_at=generated_at,
    )


def pdf_engine_available() -> bool:
    """True when WeasyPrint and its native stack are importable.

    Reported by ``/health`` so the degraded capability is visible rather than
    discovered per-request.
    """
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True


def evidence_summary(bundle: EvidenceBundle) -> dict[str, object]:
    """Compact evidentiary position, for the API preview and the UI.

    Not used in rendering; exists so the frontend can show what the packet will
    be built from without downloading the whole document.
    """
    pod = bundle.pod
    return {
        "pod_status": pod.extraction_status.value,
        "pod_carrier": pod.carrier.value,
        "pod_signature": pod.signature_captured,
        "pod_scan_count": pod.scan_count,
        "pod_ocr_confidence": pod.ocr_confidence,
        "has_delivery_timestamp": pod.delivered_at is not None,
        "three_ds_status": bundle.order.three_ds_status.value,
        "avs_match": bundle.order.avs_match,
        "cvv_match": bundle.order.cvv_match,
        "prior_dispute_count": bundle.prior_dispute_count,
        "merchant_comms_count": bundle.merchant_comms_count,
        "refund_requested": bundle.refund_requested,
        "degraded": bundle.degraded,
        "degradation_reason": bundle.degradation_reason,
        "artifact_count": len(artifact_index(bundle)),
        "is_absent": pod.extraction_status is ExtractionStatus.ABSENT,
    }
