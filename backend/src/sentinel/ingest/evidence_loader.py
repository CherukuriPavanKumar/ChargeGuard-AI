"""Evidence bundle assembly.

Gathers the three evidence modalities into one
:class:`~sentinel.schemas.evidence.EvidenceBundle`, running OCR over the
proof-of-delivery image where one is supplied.

This is the only place in the request path that touches a fallible external
dependency (the OCR engine), and it is therefore where INVARIANT 6 is enforced
at the bundle level: :func:`assemble` never raises.  Anything that goes wrong
routes through :func:`sentinel.extraction.fallback.degrade` and produces a valid
but pessimistic bundle.

Why the loader is separate from the extractor
---------------------------------------------
``extraction.ocr`` knows how to read one image.  It has no idea what an order
record is, and it should not.  This module knows how the modalities compose and
what a bundle needs to be complete.  Keeping them apart means the OCR failure
policy is stated once, in ``ocr.extract``, and the *bundle* failure policy is
stated once, here -- rather than being smeared across both.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sentinel.config import Settings, get_settings
from sentinel.extraction import fallback, ocr
from sentinel.schemas.evidence import (
    EvidenceBundle,
    ExtractionStatus,
    OrderRecord,
    ProofOfDelivery,
    SessionLog,
    ThreeDSStatus,
)

logger = logging.getLogger(__name__)


class EvidenceParseError(ValueError):
    """Raised when the order or session payload is structurally unusable.

    Distinct from an OCR failure.  A missing proof of delivery is an evidentiary
    gap the policy layer knows how to reason about; a missing *order record*
    means we do not know what was sold, and there is no pessimistic bundle that
    honestly represents that.  This one is fatal, and the caller must reject the
    request rather than score a fabrication.
    """


def _parse_datetime(value: Any, field: str) -> datetime:
    """Parse an ISO-8601 string or pass through an existing datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EvidenceParseError(
                f"{field} is not a valid ISO-8601 timestamp: {value!r}"
            ) from exc
    raise EvidenceParseError(
        f"{field} must be a timestamp, got {type(value).__name__}"
    )


def parse_order(payload: dict) -> OrderRecord:
    """Build an :class:`OrderRecord` from a raw OMS payload.

    Raises:
        EvidenceParseError: on a missing or malformed required field.
    """
    if not isinstance(payload, dict):
        raise EvidenceParseError(
            f"order payload must be an object, got {type(payload).__name__}"
        )

    required = ("order_id", "customer_name", "shipping_address", "placed_at",
                "order_total")
    missing = [key for key in required if key not in payload]
    if missing:
        raise EvidenceParseError(
            f"order payload is missing required field(s): {', '.join(missing)}"
        )

    try:
        total = Decimal(str(payload["order_total"]))
    except Exception as exc:
        raise EvidenceParseError(
            f"order_total is not numeric: {payload['order_total']!r}"
        ) from exc
    if total <= 0:
        raise EvidenceParseError(f"order_total must be positive, got {total}")

    three_ds_raw = str(payload.get("three_ds_status", "NOT_ENROLLED")).upper()
    try:
        three_ds = ThreeDSStatus(three_ds_raw)
    except ValueError:
        # An unrecognised authentication status is treated as no authentication.
        # Assuming a liability shift we cannot evidence would be the one error
        # that turns an unwinnable dispute into a filed one.
        logger.warning(
            "unrecognised 3-D Secure status %r; treating as NOT_ENROLLED",
            three_ds_raw,
        )
        three_ds = ThreeDSStatus.NOT_ENROLLED

    shipping = str(payload["shipping_address"])
    items = payload.get("items") or ()

    return OrderRecord(
        order_id=str(payload["order_id"]),
        customer_name=str(payload["customer_name"]),
        billing_address=str(payload.get("billing_address", shipping)),
        shipping_address=shipping,
        placed_at=_parse_datetime(payload["placed_at"], "placed_at"),
        items=tuple(str(item) for item in items),
        order_total=total,
        avs_match=bool(payload.get("avs_match", False)),
        cvv_match=bool(payload.get("cvv_match", False)),
        three_ds_status=three_ds,
    )


def parse_session(payload: dict) -> SessionLog:
    """Build a :class:`SessionLog` from raw checkout telemetry.

    Raises:
        EvidenceParseError: on a missing or malformed required field.
    """
    if not isinstance(payload, dict):
        raise EvidenceParseError(
            f"session payload must be an object, got {type(payload).__name__}"
        )

    required = ("ip_address", "device_fingerprint", "login_at",
                "account_created_at")
    missing = [key for key in required if key not in payload]
    if missing:
        raise EvidenceParseError(
            f"session payload is missing required field(s): {', '.join(missing)}"
        )

    try:
        lat = float(payload.get("ip_geo_lat", 0.0))
        lon = float(payload.get("ip_geo_lon", 0.0))
    except (TypeError, ValueError) as exc:
        raise EvidenceParseError(f"ip geolocation is not numeric: {exc}") from exc

    return SessionLog(
        ip_address=str(payload["ip_address"]),
        ip_geo_lat=max(-90.0, min(90.0, lat)),
        ip_geo_lon=max(-180.0, min(180.0, lon)),
        device_fingerprint=str(payload["device_fingerprint"]),
        user_agent=str(payload.get("user_agent", "")),
        login_at=_parse_datetime(payload["login_at"], "login_at"),
        account_created_at=_parse_datetime(
            payload["account_created_at"], "account_created_at"
        ),
    )


def load_pod(
    image_path: str | Path | None,
    prepared: dict | None = None,
    settings: Settings | None = None,
) -> ProofOfDelivery:
    """Resolve a proof of delivery from an image, a prepared record, or neither.

    Three sources, in precedence order:

    1. ``image_path`` -- run real OCR. This is the live path.
    2. ``prepared`` -- an already-structured POD record, used by the evaluation
       corpus (where the degradation model is numeric) and by preset fixtures.
    3. Neither -- return ``ABSENT``.

    Never raises: OCR failures come back from ``ocr.extract`` as ``UNVERIFIED``.
    """
    cfg = settings if settings is not None else get_settings()

    if image_path is not None:
        return ocr.extract(image_path, cfg)

    if prepared:
        try:
            return ProofOfDelivery.model_validate(prepared)
        except Exception as exc:
            # A malformed prepared record is a data problem, not an evidentiary
            # one, but the honest representation is still "we hold a document we
            # cannot vouch for".
            logger.warning("prepared POD record rejected: %s", exc)
            return ocr.unverified(f"prepared POD record invalid: {exc}")

    return ocr.absent()


def assemble(
    order_payload: dict,
    session_payload: dict,
    pod_image_path: str | Path | None = None,
    pod_record: dict | None = None,
    prior_dispute_count: int = 0,
    refund_requested: bool = False,
    merchant_comms_count: int = 0,
    settings: Settings | None = None,
) -> EvidenceBundle:
    """Assemble a complete evidence bundle.

    **Never raises on evidence gaps.**  An unreadable proof of delivery, a
    missing signature, or an absent document all produce a valid bundle whose
    ``extraction_status`` states the position honestly.

    Raises:
        EvidenceParseError: only when the *order* or *session* payload is
            structurally unusable. Those are not evidentiary gaps -- without
            them there is nothing to reason about, and scoring a fabricated
            order record would be worse than refusing.
    """
    cfg = settings if settings is not None else get_settings()

    order = parse_order(order_payload)
    session = parse_session(session_payload)
    pod = load_pod(pod_image_path, pod_record, cfg)

    bundle = EvidenceBundle(
        pod=pod,
        order=order,
        session=session,
        prior_dispute_count=max(0, int(prior_dispute_count)),
        refund_requested=bool(refund_requested),
        merchant_comms_count=max(0, int(merchant_comms_count)),
    )

    # A document that exists but could not be read is a degraded bundle, and the
    # audit trail should say so rather than leaving the caller to infer it from
    # the POD status alone.
    return fallback.degrade_if(
        bundle,
        pod.extraction_status is ExtractionStatus.UNVERIFIED,
        "proof-of-delivery document present but not machine-readable",
    )
