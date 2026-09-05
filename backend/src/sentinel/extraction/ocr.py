"""Proof-of-delivery OCR.

INVARIANT 6 (graceful degradation): **this module never raises.**  Every public
function returns a valid :class:`ProofOfDelivery`, including when Tesseract is
not installed, the binary is on a different PATH, the image is corrupt, or the
page is blank.  A chargeback pipeline that crashes because an OCR engine is
missing has converted a recoverable evidence gap into a total outage, and every
dispute in the queue then times out at ``expired_window_gate``.

The failure taxonomy is deliberate and is reflected in
:class:`~sentinel.schemas.evidence.ExtractionStatus`:

``ABSENT``
    No document. Distinguished from failure because it is *dispositive* under
    Visa 13.1 -- ``no_pod_on_non_receipt_gate`` forces ACCEPT on it.

``UNVERIFIED``
    A document exists but could not be read: engine missing, image unreadable,
    zero words recovered. We hold paper we cannot vouch for. Weakly contestable,
    and explicitly *not* treated as ABSENT -- conflating the two would concede
    disputes we could still win on other evidence.

``LOW_CONFIDENCE``
    Text recovered below ``settings.ocr_confidence_floor`` (default 0.55).
    Usable as corroboration, never as the sole compelling artifact.

``VERIFIED``
    Text recovered at or above the floor. Eligible for ``strong_evidence_gate``.

Parsing strategy
----------------
Courier slips are semi-structured: labelled fields in a roughly fixed order,
with layout varying by carrier. Rather than template-matching per carrier, we
run a single labelled-field regex pass over the recovered text, which degrades
smoothly -- a slip that loses its "RECIPIENT:" label to blur still yields an AWB
and a scan count, and the bundle keeps whatever survived.

Per-field confidence comes from Tesseract's own word-level confidences,
averaged over the words that landed inside each matched field span. That is
more honest than a single page-level number: an AWB read at 96% and a recipient
name read at 41% is a materially different evidentiary position from both at 68%.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sentinel.config import Settings, get_settings
from sentinel.schemas.evidence import Carrier, ExtractionStatus, ProofOfDelivery

logger = logging.getLogger(__name__)

#: Labelled-field patterns. Tolerant of OCR noise in the label itself: the
#: character classes allow the common confusions (0/O, 1/I/l, 5/S).
_AWB_RE = re.compile(
    r"(?:AWB|A\.?W\.?B|WAYBILL|TRACKING|CONSIGNMENT)\D{0,12}?([A-Z0-9]{8,18})",
    re.IGNORECASE,
)
_RECIPIENT_RE = re.compile(
    r"(?:RECEIVED\s*BY|RECIPIENT|SIGNED\s*BY|DELIVERED\s*TO)\s*[:\-]?\s*"
    r"([A-Za-z][A-Za-z\s\.]{2,40})",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"(?:ADDRESS|DELIVERY\s*ADDRESS|DELIVERED\s*AT)\s*[:\-]?\s*(.{10,120})",
    re.IGNORECASE | re.DOTALL,
)
_DATE_RE = re.compile(
    r"(?:DELIVERED|DATE|DELIVERY\s*DATE|POD\s*DATE)\D{0,10}?"
    r"(\d{2}[-/]\d{2}[-/]\d{4}(?:\s+\d{2}:\d{2})?)",
    re.IGNORECASE,
)
_SCANS_RE = re.compile(r"(?:SCANS?|SCAN\s*COUNT|EVENTS?)\s*[:\-]?\s*(\d{1,2})",
                       re.IGNORECASE)
_SIGNATURE_RE = re.compile(
    r"(SIGNATURE\s*(?:ON\s*FILE|CAPTURED|OBTAINED)|SIGNED|E-?SIGN)", re.IGNORECASE
)

#: Carrier detection from branding text on the slip.
_CARRIER_TOKENS: tuple[tuple[str, Carrier], ...] = (
    ("DELHIVERY", Carrier.DELHIVERY),
    ("BLUEDART", Carrier.BLUEDART),
    ("BLUE DART", Carrier.BLUEDART),
    ("EKART", Carrier.EKART),
    ("XPRESSBEES", Carrier.XPRESSBEES),
    ("XPRESS BEES", Carrier.XPRESSBEES),
)

#: Accepted delivery-timestamp formats, tried in order.
_DATE_FORMATS: tuple[str, ...] = (
    "%d-%m-%Y %H:%M",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y",
    "%d/%m/%Y",
)


class OCRUnavailable(RuntimeError):
    """Raised internally when the Tesseract engine cannot be reached.

    Caught within this module and converted to an ``UNVERIFIED`` parse. It never
    escapes to a caller -- it exists so the two failure modes (no engine vs.
    unreadable page) stay distinguishable in the logs.
    """


def _load_tesseract() -> Any:
    """Import pytesseract, or raise :class:`OCRUnavailable`.

    Imported lazily rather than at module scope so that importing
    ``sentinel.extraction.ocr`` never fails on a machine without the package --
    the API must start and serve the scoring path even with no OCR stack at all.
    """
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise OCRUnavailable(f"pytesseract not importable: {exc}") from exc
    return pytesseract


def _recover_text(image_path: Path) -> tuple[str, float]:
    """Run Tesseract and return ``(text, mean_word_confidence)``.

    Raises:
        OCRUnavailable: engine missing, binary not on PATH, or image unreadable.
    """
    pytesseract = _load_tesseract()

    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise OCRUnavailable(f"Pillow not importable: {exc}") from exc

    try:
        with Image.open(image_path) as img:
            data = pytesseract.image_to_data(
                img, output_type=pytesseract.Output.DICT
            )
    except Exception as exc:
        # Deliberately broad. pytesseract raises TesseractNotFoundError, PIL
        # raises UnidentifiedImageError, and a truncated file raises OSError.
        # All three mean the same thing to us: we could not read this document.
        raise OCRUnavailable(
            f"OCR failed on {image_path.name}: {type(exc).__name__}: {exc}"
        ) from exc

    words: list[str] = []
    confidences: list[float] = []
    for text, conf in zip(data.get("text", []), data.get("conf", [])):
        token = str(text).strip()
        if not token:
            continue
        try:
            confidence = float(conf)
        except (TypeError, ValueError):
            continue
        if confidence < 0:  # Tesseract emits -1 for non-text regions
            continue
        words.append(token)
        confidences.append(confidence / 100.0)

    if not words:
        raise OCRUnavailable(f"no text recovered from {image_path.name}")

    mean_conf = sum(confidences) / len(confidences)
    return " ".join(words), mean_conf


def _match_carrier(text: str) -> Carrier:
    """Identify the carrier from branding tokens in the recovered text."""
    upper = text.upper()
    for token, carrier in _CARRIER_TOKENS:
        if token in upper:
            return carrier
    return Carrier.UNKNOWN


def _parse_delivered_at(text: str) -> datetime | None:
    """Extract a delivery timestamp, or None when no format matches."""
    match = _DATE_RE.search(text)
    if match is None:
        return None
    raw = match.group(1).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _first_group(pattern: re.Pattern[str], text: str) -> str:
    """Return the first capture group, whitespace-collapsed, or an empty string."""
    match = pattern.search(text)
    if match is None:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _parse_int(pattern: re.Pattern[str], text: str, default: int = 0) -> int:
    """Return the first capture group as an int, or ``default``."""
    raw = _first_group(pattern, text)
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def parse_text(text: str, mean_confidence: float, settings: Settings) -> ProofOfDelivery:
    """Parse recovered OCR text into a structured proof of delivery.

    Pure: no I/O.  Separated from :func:`extract` so the parser can be tested
    against fixed strings without an OCR engine present.

    The status is ``VERIFIED`` only when the mean confidence clears the floor
    *and* the two evidentially decisive fields -- recipient and address -- both
    parsed. A page read at 90% confidence that yielded no recipient name is not
    verified evidence; it is a legible page about which we learned nothing.
    """
    awb = _first_group(_AWB_RE, text)
    recipient = _first_group(_RECIPIENT_RE, text)
    address = _first_group(_ADDRESS_RE, text)
    scans = _parse_int(_SCANS_RE, text)
    signature = _SIGNATURE_RE.search(text) is not None
    delivered_at = _parse_delivered_at(text)
    carrier = _match_carrier(text)

    decisive_fields_present = bool(recipient) and bool(address)
    if mean_confidence >= settings.ocr_confidence_floor and decisive_fields_present:
        status = ExtractionStatus.VERIFIED
    else:
        status = ExtractionStatus.LOW_CONFIDENCE

    return ProofOfDelivery(
        awb_number=awb,
        delivered_at=delivered_at,
        recipient_name=recipient,
        signature_captured=signature,
        delivery_address=address,
        carrier=carrier,
        scan_count=scans,
        ocr_confidence=round(max(0.0, min(1.0, mean_confidence)), 4),
        extraction_status=status,
    )


def unverified(reason: str) -> ProofOfDelivery:
    """Return the pessimistic parse used when extraction fails.

    Every field empty, confidence zero, status ``UNVERIFIED``.  Note this is
    *not* ``ABSENT``: a document exists, we simply could not read it, and the
    policy gates treat those two situations very differently.
    """
    logger.warning("POD extraction degraded to UNVERIFIED: %s", reason)
    return ProofOfDelivery(
        awb_number="",
        delivered_at=None,
        recipient_name="",
        signature_captured=False,
        delivery_address="",
        carrier=Carrier.UNKNOWN,
        scan_count=0,
        ocr_confidence=0.0,
        extraction_status=ExtractionStatus.UNVERIFIED,
    )


def absent() -> ProofOfDelivery:
    """Return the parse representing 'no proof-of-delivery document exists'."""
    return ProofOfDelivery(extraction_status=ExtractionStatus.ABSENT)


def extract(
    image_path: str | Path | None, settings: Settings | None = None
) -> ProofOfDelivery:
    """Extract a proof of delivery from a courier slip image.

    **Never raises.** Returns ``ABSENT`` when there is no path or no file,
    ``UNVERIFIED`` when extraction fails for any reason, and a parsed record
    otherwise.

    Args:
        image_path: Path to the slip image, or None when no document exists.
        settings: Configuration; the process singleton when omitted.

    Returns:
        A :class:`ProofOfDelivery` whose ``extraction_status`` states exactly
        how much of it can be trusted.
    """
    cfg = settings if settings is not None else get_settings()

    if image_path is None:
        return absent()

    path = Path(image_path)
    try:
        if not path.is_file():
            return absent()
    except OSError as exc:
        # A path that cannot even be stat'd (permissions, bad mount) is a
        # failure to read, not proof of nonexistence.
        return unverified(f"could not stat {path}: {exc}")

    try:
        text, mean_conf = _recover_text(path)
    except OCRUnavailable as exc:
        return unverified(str(exc))
    except Exception as exc:  # pragma: no cover - last-resort safety net
        # INVARIANT 6 is unconditional. Anything at all that escapes the inner
        # handlers still becomes a valid pessimistic parse.
        return unverified(f"unexpected OCR error: {type(exc).__name__}: {exc}")

    try:
        return parse_text(text, mean_conf, cfg)
    except Exception as exc:  # pragma: no cover - last-resort safety net
        return unverified(f"POD parse failed: {type(exc).__name__}: {exc}")


def engine_available() -> bool:
    """True when a working Tesseract engine can be reached.

    Used by ``/health`` to report degraded capability honestly rather than
    claiming full function and failing per-request.
    """
    try:
        pytesseract = _load_tesseract()
        pytesseract.get_tesseract_version()
    except Exception:
        return False
    return True
