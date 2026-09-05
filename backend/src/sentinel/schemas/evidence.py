"""Evidence-side value objects.

Everything the merchant can put in front of the issuer.  Three independent
modalities are modelled, because chargeback defence is fundamentally a
multi-modal problem:

* **Image**     -- the courier's proof-of-delivery slip, read by OCR.
* **Tabular**   -- the order record from the merchant's own OMS.
* **Telemetry** -- the session log captured at checkout.

Crucially every field here is an *observation*, not a fact.  OCR misreads.
Carriers mis-key recipient names.  IP geolocation is coarse.  The
``extraction_status`` and ``ocr_confidence`` fields exist so that downstream
code can reason about how much to trust what it is holding, and so that the
policy gates can refuse to contest on evidence that would not survive an
issuer's review.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class ExtractionStatus(StrEnum):
    """How much the system trusts the parsed proof-of-delivery.

    This is a first-class part of the decision surface, not a logging detail:
    ``no_pod_on_non_receipt_gate`` hard-forces ACCEPT on ``ABSENT``.
    """

    VERIFIED = "VERIFIED"
    """OCR succeeded with mean per-field confidence at or above the trust floor."""

    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    """OCR produced text but below the trust floor; usable as weak evidence."""

    UNVERIFIED = "UNVERIFIED"
    """Extraction was attempted and failed (engine missing, image corrupt).
    A POD document may exist, but ChargeGuard cannot vouch for its contents."""

    ABSENT = "ABSENT"
    """No proof-of-delivery document exists at all."""


class ThreeDSStatus(StrEnum):
    """3-D Secure authentication outcome for the original authorisation.

    ``AUTHENTICATED`` is the only value that carries a liability shift to the
    issuer, which is why it is the hinge of
    ``fraud_without_liability_shift_gate``.
    """

    AUTHENTICATED = "AUTHENTICATED"
    ATTEMPTED = "ATTEMPTED"
    NOT_ENROLLED = "NOT_ENROLLED"
    FAILED = "FAILED"


class Carrier(StrEnum):
    """Indian last-mile carriers whose POD formats ChargeGuard can parse."""

    DELHIVERY = "DELHIVERY"
    BLUEDART = "BLUEDART"
    EKART = "EKART"
    XPRESSBEES = "XPRESSBEES"
    UNKNOWN = "UNKNOWN"


class ProofOfDelivery(BaseModel):
    """Parsed contents of a courier proof-of-delivery slip.

    Populated either by ``sentinel.extraction.ocr`` (live path) or by the
    synthetic generator's degradation model (training path).  Field values are
    whatever was *read*, which may differ from what was printed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    awb_number: str = Field(
        default="",
        description="Air waybill / tracking number as read from the slip.",
    )
    delivered_at: datetime | None = Field(
        default=None,
        description="Delivery timestamp parsed from the slip, if legible.",
    )
    recipient_name: str = Field(
        default="",
        description="Name of the person who signed for the parcel, as read.",
    )
    signature_captured: bool = Field(
        default=False,
        description=(
            "Whether a signature glyph was detected on the slip. Signature "
            "capture is compelling evidence under Visa 13.1."
        ),
    )
    delivery_address: str = Field(
        default="",
        description="Delivery address block as read from the slip.",
    )
    carrier: Carrier = Field(
        default=Carrier.UNKNOWN,
        description="Carrier whose template the slip matched.",
    )
    scan_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Number of network scan events on the shipment. A dense scan trail "
            "is corroborating evidence of genuine physical movement."
        ),
    )
    ocr_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Mean per-field OCR confidence in [0,1].",
    )
    extraction_status: ExtractionStatus = Field(
        default=ExtractionStatus.ABSENT,
        description="Trust level assigned to this parse.",
    )

    @property
    def is_usable(self) -> bool:
        """True when the parse is good enough to cite in a representment."""
        return self.extraction_status in (
            ExtractionStatus.VERIFIED,
            ExtractionStatus.LOW_CONFIDENCE,
        )


class OrderRecord(BaseModel):
    """The merchant's own record of what was sold, to whom, and how it paid."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str = Field(..., min_length=1, description="Merchant order identifier.")
    customer_name: str = Field(
        ...,
        description="Customer name on the order, as captured at checkout.",
    )
    billing_address: str = Field(
        ...,
        description="Billing address supplied at checkout.",
    )
    shipping_address: str = Field(
        ...,
        description="Shipping address the parcel was despatched to.",
    )
    placed_at: datetime = Field(..., description="Order placement timestamp (UTC).")
    items: tuple[str, ...] = Field(
        default=(),
        description=(
            "Line-item descriptions. A tuple rather than a list so the frozen "
            "model is genuinely immutable rather than merely assignment-proof."
        ),
    )
    order_total: Decimal = Field(
        ...,
        gt=0,
        description="Total order value in INR (may exceed the disputed amount).",
    )
    avs_match: bool = Field(
        ...,
        description="Address Verification Service match on the authorisation.",
    )
    cvv_match: bool = Field(
        ...,
        description="CVV2/CVC2 match on the authorisation.",
    )
    three_ds_status: ThreeDSStatus = Field(
        ...,
        description="3-D Secure outcome; the source of any liability shift.",
    )

    @field_serializer("order_total")
    def _ser_total(self, v: Decimal) -> float:
        """Emit rupee amounts as JSON numbers so the frontend can do arithmetic."""
        return float(v)

    @property
    def liability_shifted(self) -> bool:
        """True when the issuer, not the merchant, bears fraud liability."""
        return self.three_ds_status is ThreeDSStatus.AUTHENTICATED


class SessionLog(BaseModel):
    """Checkout-session telemetry.

    Behavioural evidence: where the buyer was, on what device, and how long the
    account had existed.  Under Visa 10.4 with no liability shift this is often
    the only compelling evidence available.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ip_address: str = Field(..., description="Client IP observed at checkout.")
    ip_geo_lat: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Geolocated latitude of the client IP.",
    )
    ip_geo_lon: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Geolocated longitude of the client IP.",
    )
    device_fingerprint: str = Field(
        ...,
        description=(
            "Stable device hash. Repeats across unrelated disputes are the "
            "signature of a coordinated friendly-fraud ring."
        ),
    )
    user_agent: str = Field(..., description="Raw User-Agent string at checkout.")
    login_at: datetime = Field(
        ...,
        description="Timestamp of the authenticated session start (UTC).",
    )
    account_created_at: datetime = Field(
        ...,
        description="Account registration timestamp (UTC).",
    )

    @property
    def is_mobile(self) -> bool:
        """Coarse mobile detection from the User-Agent string."""
        ua = self.user_agent.lower()
        return any(token in ua for token in ("android", "iphone", "ipad", "mobile"))


class EvidenceBundle(BaseModel):
    """Everything ChargeGuard holds about one dispute, across all modalities.

    This object plus a :class:`~sentinel.schemas.dispute.DisputeEvent` is the
    complete input to the feature builder.  Nothing else is ever read.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pod: ProofOfDelivery = Field(
        default_factory=ProofOfDelivery,
        description="Parsed proof of delivery. Defaults to an ABSENT parse.",
    )
    order: OrderRecord = Field(
        ...,
        description="Merchant order record for the disputed transaction.",
    )
    session: SessionLog = Field(..., description="Checkout session telemetry.")
    prior_dispute_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Prior disputes raised by this cardholder against this merchant. "
            "High counts are the signature of friendly-fraud recidivism."
        ),
    )
    refund_requested: bool = Field(
        default=False,
        description=(
            "Whether a refund was requested or issued before the chargeback "
            "was raised. Decisive for VISA_13.6."
        ),
    )
    merchant_comms_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Number of logged merchant-to-customer contacts. Documented "
            "engagement is compelling evidence that the buyer knew the merchant."
        ),
    )
    degraded: bool = Field(
        default=False,
        description=(
            "True when this bundle was produced by "
            "``sentinel.extraction.fallback.degrade`` after an upstream failure."
        ),
    )
    degradation_reason: str = Field(
        default="",
        description="Human-readable cause of degradation; empty when healthy.",
    )
