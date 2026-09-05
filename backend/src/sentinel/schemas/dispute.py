"""Dispute-side value objects.

These model the inbound chargeback notification exactly as a card network
(via the acquirer / Razorpay dispute webhook) presents it.  Nothing in this
module knows anything about evidence, models, or decisions -- it is the raw
adversarial input to the system.

All models are frozen: a dispute event is an immutable historical fact.  If
the network sends an update, that is a *new* event, not a mutation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class ReasonCode(StrEnum):
    """Card-scheme dispute reason codes handled by ChargeGuard.

    The reason code is the single most important categorical input: it
    determines which evidence is *compelling* under scheme rules, and
    therefore which policy gates are even applicable.
    """

    VISA_10_4 = "VISA_10.4"
    """Visa 10.4 -- Other Fraud, Card-Absent Environment.  The cardholder
    denies participating.  Winnable only with a liability shift (3-D Secure)
    or overwhelming compelling evidence of prior undisputed use."""

    VISA_13_1 = "VISA_13.1"
    """Visa 13.1 -- Merchandise / Services Not Received.  Proof of delivery
    to the cardholder's address is the decisive artifact."""

    VISA_13_3 = "VISA_13.3"
    """Visa 13.3 -- Not as Described or Defective Merchandise.  Requires
    product description evidence and returns-policy disclosure."""

    VISA_13_6 = "VISA_13.6"
    """Visa 13.6 -- Credit Not Processed.  Indefensible if a refund was in
    fact already issued; strong if no refund was ever owed."""

    MC_4837 = "MC_4837"
    """Mastercard 4837 -- No Cardholder Authorisation.  Mastercard analogue
    of Visa 10.4."""

    MC_4853 = "MC_4853"
    """Mastercard 4853 -- Cardholder Dispute (goods/services).  Umbrella code
    covering not-received and not-as-described."""


#: Reason codes whose core allegation is "I did not make this transaction".
FRAUD_REASON_CODES: frozenset[ReasonCode] = frozenset(
    {ReasonCode.VISA_10_4, ReasonCode.MC_4837}
)

#: Reason codes whose core allegation is "the goods never arrived".
NON_RECEIPT_REASON_CODES: frozenset[ReasonCode] = frozenset(
    {ReasonCode.VISA_13_1, ReasonCode.MC_4853}
)


class CardNetwork(StrEnum):
    """Acquiring network that raised the dispute."""

    VISA = "VISA"
    MASTERCARD = "MASTERCARD"
    RUPAY = "RUPAY"


class DisputeEvent(BaseModel):
    """An inbound chargeback notification.

    ``amount_inr`` is the amount at risk.  It is the ``A_i`` of the core
    arbitrage inequality ``p_i * A_i >= lambda * c`` and is therefore the
    single most consequential number in the system.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dispute_id: str = Field(
        ...,
        min_length=1,
        description="Acquirer-assigned unique identifier for this dispute.",
    )
    transaction_id: str = Field(
        ...,
        min_length=1,
        description="Identifier of the original captured payment being disputed.",
    )
    merchant_id: str = Field(
        ...,
        min_length=1,
        description="Merchant account under which the transaction was captured.",
    )
    reason_code: ReasonCode = Field(
        ...,
        description="Card-scheme reason code asserted by the issuing bank.",
    )
    amount_inr: Decimal = Field(
        ...,
        gt=0,
        description="Disputed amount in Indian rupees. The 'A_i' of the EV rule.",
    )
    currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
        description="ISO-4217 currency code. ChargeGuard operates on INR settlements.",
    )
    disputed_at: datetime = Field(
        ...,
        description="Timestamp at which the issuer raised the dispute (UTC).",
    )
    respond_by: datetime = Field(
        ...,
        description="Scheme-mandated representment deadline (UTC). Past this "
        "instant the dispute is unwinnable at any probability.",
    )
    network: CardNetwork = Field(
        ...,
        description="Card network that raised the dispute.",
    )

    @field_validator("currency")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        return v.upper()

    @field_serializer("amount_inr")
    def _ser_amount(self, v: Decimal) -> float:
        """Serialise rupee amounts as JSON numbers, not strings.

        The frontend performs arithmetic on these values; emitting Decimal as
        a string would silently produce string concatenation in JavaScript.
        """
        return float(v)

    @property
    def hours_remaining(self) -> float:
        """Hours left before the representment window closes.

        Computed against ``respond_by`` and the current wall clock.  This is a
        *presentation* property and is deliberately NOT used by
        ``sentinel.features.builder`` (which must stay pure); the feature
        builder derives its time-to-deadline feature from
        ``respond_by - disputed_at`` instead.

        Returns a negative number once the window has expired.
        """
        now = datetime.now(timezone.utc)
        deadline = self.respond_by
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return (deadline - now).total_seconds() / 3600.0

    @property
    def window_hours(self) -> float:
        """Total width of the representment window, in hours.

        Clock-free: derived purely from two fields on the event itself, so it
        is safe for the pure feature builder to consume.
        """
        start, end = self.disputed_at, self.respond_by
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return (end - start).total_seconds() / 3600.0

    @property
    def is_fraud_code(self) -> bool:
        """True when the allegation is 'I did not authorise this'."""
        return self.reason_code in FRAUD_REASON_CODES

    @property
    def is_non_receipt_code(self) -> bool:
        """True when the allegation is 'the goods never arrived'."""
        return self.reason_code in NON_RECEIPT_REASON_CODES
