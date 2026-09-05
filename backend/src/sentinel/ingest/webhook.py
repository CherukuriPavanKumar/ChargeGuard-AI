"""Inbound dispute webhook adapter.

Translates an acquirer's webhook envelope into a
:class:`~sentinel.schemas.dispute.DisputeEvent`.  The shape modelled here follows
the Razorpay dispute webhook convention: a typed envelope wrapping a
``payload.dispute.entity`` object with epoch-second timestamps and amounts in
paise.

Two conversions matter and are easy to get wrong:

**Paise to rupees.**  Acquirer APIs carry amounts as integer minor units.
Dividing by 100 in floating point introduces representation error into the one
number the entire economic argument multiplies, so the conversion goes through
:class:`~decimal.Decimal` and never touches a float.

**Epoch seconds to aware datetimes.**  Naive datetimes silently compare as local
time somewhere downstream. Everything here is UTC-aware from the boundary in.

The adapter is strict: an envelope it does not recognise raises
:class:`WebhookParseError` rather than guessing.  Guessing at the boundary is how
a malformed amount becomes a wrong decision.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sentinel.schemas.dispute import CardNetwork, DisputeEvent, ReasonCode

#: Acquirer reason-code strings mapped onto the internal vocabulary. Acquirers
#: are inconsistent about punctuation and casing, so several spellings map to
#: the same member.
REASON_CODE_ALIASES: dict[str, ReasonCode] = {
    "10.4": ReasonCode.VISA_10_4,
    "VISA_10.4": ReasonCode.VISA_10_4,
    "VISA_10_4": ReasonCode.VISA_10_4,
    "13.1": ReasonCode.VISA_13_1,
    "VISA_13.1": ReasonCode.VISA_13_1,
    "VISA_13_1": ReasonCode.VISA_13_1,
    "13.3": ReasonCode.VISA_13_3,
    "VISA_13.3": ReasonCode.VISA_13_3,
    "VISA_13_3": ReasonCode.VISA_13_3,
    "13.6": ReasonCode.VISA_13_6,
    "VISA_13.6": ReasonCode.VISA_13_6,
    "VISA_13_6": ReasonCode.VISA_13_6,
    "4837": ReasonCode.MC_4837,
    "MC_4837": ReasonCode.MC_4837,
    "4853": ReasonCode.MC_4853,
    "MC_4853": ReasonCode.MC_4853,
}

#: Acquirer network strings mapped onto the internal vocabulary.
NETWORK_ALIASES: dict[str, CardNetwork] = {
    "VISA": CardNetwork.VISA,
    "MC": CardNetwork.MASTERCARD,
    "MASTERCARD": CardNetwork.MASTERCARD,
    "MASTER": CardNetwork.MASTERCARD,
    "RUPAY": CardNetwork.RUPAY,
}

#: Fallback representment window when the acquirer omits a deadline. Seven days
#: is the shortest scheme window in common use, so assuming it errs toward
#: treating a dispute as more urgent than it is -- the safe direction.
DEFAULT_WINDOW_HOURS: float = 7 * 24.0


class WebhookParseError(ValueError):
    """Raised when an inbound envelope cannot be parsed into a DisputeEvent.

    Distinct from a validation error on a well-formed payload: this means the
    envelope itself was not the shape we expect, and no amount of coercion will
    recover it.
    """


def _epoch_to_utc(value: Any, field: str) -> datetime:
    """Convert epoch seconds, or an ISO-8601 string, to an aware UTC datetime."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WebhookParseError(
                f"{field} is not a valid ISO-8601 timestamp: {value!r}"
            ) from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    raise WebhookParseError(f"{field} has unsupported type {type(value).__name__}")


def paise_to_rupees(paise: Any) -> Decimal:
    """Convert integer minor units to an exact rupee :class:`Decimal`.

    Never routes through float.  ``12345 / 100`` in binary floating point is
    ``123.45000000000000284...``, and that error would propagate into every
    expected-value computation for the life of the dispute.
    """
    try:
        minor = Decimal(str(paise))
    except Exception as exc:
        raise WebhookParseError(f"amount is not numeric: {paise!r}") from exc

    if minor != minor.to_integral_value():
        raise WebhookParseError(
            f"amount in paise must be an integer, got {paise!r}"
        )
    return (minor / Decimal("100")).quantize(Decimal("0.01"))


def parse_reason_code(raw: Any) -> ReasonCode:
    """Map an acquirer reason-code string onto the internal enum."""
    if isinstance(raw, ReasonCode):
        return raw
    key = str(raw).strip().upper()
    if key in REASON_CODE_ALIASES:
        return REASON_CODE_ALIASES[key]
    raise WebhookParseError(
        f"unrecognised reason code {raw!r}; supported: "
        f"{sorted(set(c.value for c in ReasonCode))}"
    )


def parse_network(raw: Any, reason_code: ReasonCode) -> CardNetwork:
    """Map an acquirer network string, inferring from the reason code if absent.

    Reason codes are network-specific, so an omitted network is recoverable
    rather than fatal: a ``13.1`` is by definition a Visa dispute.
    """
    if raw is not None:
        key = str(raw).strip().upper()
        if key in NETWORK_ALIASES:
            return NETWORK_ALIASES[key]
    return (
        CardNetwork.VISA
        if reason_code.value.startswith("VISA")
        else CardNetwork.MASTERCARD
    )


def parse_dispute_webhook(envelope: dict) -> DisputeEvent:
    """Parse an acquirer dispute webhook into a :class:`DisputeEvent`.

    Accepts either the full envelope (``{"event": ..., "payload": {...}}``) or a
    bare dispute entity, since acquirers differ and replayed events are often
    stored unwrapped.

    Args:
        envelope: The decoded JSON body.

    Returns:
        A validated :class:`DisputeEvent`.

    Raises:
        WebhookParseError: if the envelope is not recognisable, or a required
            field is missing or malformed.
    """
    if not isinstance(envelope, dict):
        raise WebhookParseError(
            f"envelope must be an object, got {type(envelope).__name__}"
        )

    entity: dict = envelope
    payload = envelope.get("payload")
    if isinstance(payload, dict):
        dispute_wrapper = payload.get("dispute")
        if isinstance(dispute_wrapper, dict):
            candidate = dispute_wrapper.get("entity", dispute_wrapper)
            if isinstance(candidate, dict):
                entity = candidate

    required = ("id", "payment_id", "reason_code", "amount")
    missing = [key for key in required if key not in entity]
    if missing:
        raise WebhookParseError(
            f"dispute entity is missing required field(s): {', '.join(missing)}"
        )

    reason_code = parse_reason_code(entity["reason_code"])
    amount = paise_to_rupees(entity["amount"])

    created_raw = entity.get("created_at")
    disputed_at = (
        _epoch_to_utc(created_raw, "created_at")
        if created_raw is not None
        else datetime.now(timezone.utc)
    )

    respond_raw = entity.get("respond_by")
    if respond_raw is not None:
        respond_by = _epoch_to_utc(respond_raw, "respond_by")
    else:
        respond_by = disputed_at + timedelta(hours=DEFAULT_WINDOW_HOURS)

    if respond_by <= disputed_at:
        raise WebhookParseError(
            f"respond_by ({respond_by.isoformat()}) must be after created_at "
            f"({disputed_at.isoformat()})"
        )

    return DisputeEvent(
        dispute_id=str(entity["id"]),
        transaction_id=str(entity["payment_id"]),
        merchant_id=str(entity.get("merchant_id", "acc_unknown")),
        reason_code=reason_code,
        amount_inr=amount,
        currency=str(entity.get("currency", "INR")),
        disputed_at=disputed_at,
        respond_by=respond_by,
        network=parse_network(entity.get("network"), reason_code),
    )


def to_webhook_envelope(dispute: DisputeEvent) -> dict:
    """Render a :class:`DisputeEvent` back into acquirer envelope shape.

    The inverse of :func:`parse_dispute_webhook`, used to build round-trip
    fixtures and to populate the simulate endpoint's request examples so the API
    documentation shows a realistic payload rather than an invented one.
    """
    return {
        "entity": "event",
        "event": "payment.dispute.created",
        "contains": ["dispute"],
        "payload": {
            "dispute": {
                "entity": {
                    "id": dispute.dispute_id,
                    "payment_id": dispute.transaction_id,
                    "merchant_id": dispute.merchant_id,
                    "amount": int(dispute.amount_inr * 100),
                    "currency": dispute.currency,
                    "reason_code": dispute.reason_code.value,
                    "network": dispute.network.value,
                    "created_at": int(dispute.disputed_at.timestamp()),
                    "respond_by": int(dispute.respond_by.timestamp()),
                }
            }
        },
    }
