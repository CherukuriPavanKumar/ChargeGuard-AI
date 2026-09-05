"""The feature contract.

A :class:`FeatureVector` is the *only* thing the win-probability model is ever
allowed to see.  It is frozen and versioned, which buys three things:

1. **Reproducibility.**  ``feature_version`` is stamped into every
   :class:`~sentinel.schemas.decision.Decision`, so a decision made months ago
   can be explained with the feature semantics that were live at the time.
2. **Train/serve symmetry.**  The same builder produces the training matrix and
   the serving vector.  There is no second code path to drift.
3. **Auditability.**  Every field is named and typed.  There is no anonymous
   ``float[35]`` floating through the system.

Field order is declaration order and is asserted against
``sentinel.features.registry.REGISTRY`` at import time.  Reordering fields here
without reordering the registry raises immediately rather than silently
permuting the model's input columns.
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

#: Bumped whenever the meaning, order, or membership of the feature set changes.
FEATURE_VERSION: str = "v1"


class FeatureVector(BaseModel):
    """35 named, ordered, numeric observations describing one dispute.

    Every field is a *noisy observation*, never a latent truth.  The synthetic
    generator deliberately withholds its latent winnability score; see
    ``data_gen.generator`` for the data-generating process and the ceiling it
    places on achievable AUC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    feature_version: str = Field(
        default=FEATURE_VERSION,
        description="Version tag of the feature contract that produced this vector.",
    )

    # ---------------------------------------------------------------- #
    # Family: TRANSACTION                                              #
    # What is at stake, under which scheme rule, on which network.     #
    # ---------------------------------------------------------------- #
    amount_inr: float = Field(
        ..., description="Disputed amount in rupees. The 'A_i' of the EV rule."
    )
    log_amount: float = Field(
        ..., description="Natural log of (1 + disputed amount); tames the long tail."
    )
    amount_to_order_ratio: float = Field(
        ...,
        description=(
            "Disputed amount divided by total order value. A partial dispute "
            "(<1.0) often signals a specific line-item complaint rather than "
            "blanket fraud denial."
        ),
    )
    window_hours: float = Field(
        ...,
        description=(
            "Width of the representment window in hours, computed clock-free as "
            "respond_by minus disputed_at."
        ),
    )
    reason_is_fraud: int = Field(
        ..., description="1 when the reason code is VISA_10.4 or MC_4837."
    )
    reason_is_non_receipt: int = Field(
        ..., description="1 when the reason code is VISA_13.1 or MC_4853."
    )
    reason_is_not_as_described: int = Field(
        ..., description="1 when the reason code is VISA_13.3."
    )
    reason_is_credit_not_processed: int = Field(
        ..., description="1 when the reason code is VISA_13.6."
    )
    network_is_visa: int = Field(
        ..., description="1 for Visa, 0 for Mastercard or RuPay."
    )

    # ---------------------------------------------------------------- #
    # Family: FULFILMENT                                               #
    # Did the parcel physically reach the cardholder's address?        #
    # ---------------------------------------------------------------- #
    pod_present: int = Field(
        ..., description="1 when a proof-of-delivery parse exists at any trust level."
    )
    pod_verified: int = Field(
        ..., description="1 when extraction_status is VERIFIED."
    )
    pod_low_confidence: int = Field(
        ..., description="1 when extraction_status is LOW_CONFIDENCE."
    )
    pod_signature_captured: int = Field(
        ..., description="1 when a signature glyph was detected on the slip."
    )
    pod_scan_count: int = Field(
        ..., description="Carrier network scan events on the shipment."
    )
    pod_ocr_confidence: float = Field(
        ..., description="Mean per-field OCR confidence in [0,1]; 0.0 when absent."
    )
    delivery_lag_hours: float = Field(
        ...,
        description=(
            "Hours from order placement to delivery scan. Negative sentinel "
            "(-1.0) when no delivery timestamp was legible."
        ),
    )
    delivered_before_dispute: int = Field(
        ...,
        description=(
            "1 when the delivery scan predates the chargeback. Delivery after "
            "the dispute is raised is not compelling evidence."
        ),
    )
    recipient_name_match: float = Field(
        ...,
        description=(
            "Fuzzy token-set similarity in [0,1] between the POD recipient and "
            "the order customer name."
        ),
    )
    delivery_address_match: float = Field(
        ...,
        description=(
            "Fuzzy token-set similarity in [0,1] between the POD delivery "
            "address and the order shipping address."
        ),
    )

    # ---------------------------------------------------------------- #
    # Family: BEHAVIOURAL                                              #
    # Who was on the other end of the session, and how do they behave? #
    # ---------------------------------------------------------------- #
    prior_dispute_count: int = Field(
        ..., description="Prior disputes by this cardholder against this merchant."
    )
    account_age_days: float = Field(
        ...,
        description=(
            "Days between account creation and order placement. Accounts minted "
            "hours before a large order are a classic friendly-fraud tell."
        ),
    )
    login_to_order_minutes: float = Field(
        ...,
        description=(
            "Minutes from authenticated session start to order placement. "
            "Sub-minute values indicate scripted checkout."
        ),
    )
    ip_offshore_distance_km: float = Field(
        ...,
        description=(
            "Great-circle distance in km from the checkout IP to the Indian "
            "landmass centroid. A fixed constant is used as the reference so "
            "this feature stays a pure function of its inputs."
        ),
    )
    ip_is_offshore: int = Field(
        ..., description="1 when the checkout IP geolocates more than 2500 km from India."
    )
    user_agent_is_mobile: int = Field(
        ..., description="1 when the checkout User-Agent is a mobile browser."
    )
    merchant_comms_count: int = Field(
        ..., description="Logged merchant-to-customer contacts before the dispute."
    )
    refund_requested: int = Field(
        ..., description="1 when a refund was requested or issued pre-chargeback."
    )

    # ---------------------------------------------------------------- #
    # Family: EVIDENCE COMPLETENESS                                    #
    # How strong is the paper trail we could actually put in front of  #
    # the issuer, independent of whether the merchant is in the right? #
    # ---------------------------------------------------------------- #
    avs_match: int = Field(..., description="1 when AVS matched on the authorisation.")
    cvv_match: int = Field(..., description="1 when CVV matched on the authorisation.")
    three_ds_authenticated: int = Field(
        ..., description="1 when 3-D Secure returned AUTHENTICATED."
    )
    three_ds_failed: int = Field(
        ..., description="1 when 3-D Secure returned FAILED."
    )
    liability_shift: int = Field(
        ...,
        description=(
            "1 when fraud liability sits with the issuer. Under a fraud reason "
            "code this is very nearly dispositive."
        ),
    )
    billing_shipping_match: float = Field(
        ...,
        description=(
            "Fuzzy similarity in [0,1] between billing and shipping addresses. "
            "Divergence is a fraud signal but also an ordinary gifting pattern."
        ),
    )
    item_count: int = Field(..., description="Number of line items on the order.")
    evidence_completeness_score: float = Field(
        ...,
        description=(
            "Composite in [0,1] summarising how many independent corroborating "
            "artifacts are present. Not a probability and never treated as one."
        ),
    )

    # ------------------------------------------------------------------ #
    # Ordering contract                                                  #
    # ------------------------------------------------------------------ #

    #: Canonical column order for the model matrix. Declaration order, minus the
    #: non-numeric ``feature_version`` tag. Asserted against the registry.
    NUMERIC_FIELDS: ClassVar[tuple[str, ...]] = (
        # transaction
        "amount_inr",
        "log_amount",
        "amount_to_order_ratio",
        "window_hours",
        "reason_is_fraud",
        "reason_is_non_receipt",
        "reason_is_not_as_described",
        "reason_is_credit_not_processed",
        "network_is_visa",
        # fulfilment
        "pod_present",
        "pod_verified",
        "pod_low_confidence",
        "pod_signature_captured",
        "pod_scan_count",
        "pod_ocr_confidence",
        "delivery_lag_hours",
        "delivered_before_dispute",
        "recipient_name_match",
        "delivery_address_match",
        # behavioural
        "prior_dispute_count",
        "account_age_days",
        "login_to_order_minutes",
        "ip_offshore_distance_km",
        "ip_is_offshore",
        "user_agent_is_mobile",
        "merchant_comms_count",
        "refund_requested",
        # evidence completeness
        "avs_match",
        "cvv_match",
        "three_ds_authenticated",
        "three_ds_failed",
        "liability_shift",
        "billing_shipping_match",
        "item_count",
        "evidence_completeness_score",
    )

    def to_array(self) -> np.ndarray:
        """Return the feature values as a float64 array in registry order.

        Shape is ``(1, len(NUMERIC_FIELDS))`` so it drops straight into
        LightGBM's ``predict`` without a reshape at the call site.
        """
        values = [float(getattr(self, name)) for name in self.NUMERIC_FIELDS]
        return np.asarray([values], dtype=np.float64)

    def to_flat_dict(self) -> dict[str, float]:
        """Return an ordered name -> value mapping, for audit records and logs."""
        return {name: float(getattr(self, name)) for name in self.NUMERIC_FIELDS}


#: Public, import-time-stable column order. Everything that builds a matrix
#: (training, evaluation, serving) reads this and only this.
FEATURE_ORDER: tuple[str, ...] = FeatureVector.NUMERIC_FIELDS

assert len(FEATURE_ORDER) == len(set(FEATURE_ORDER)), "duplicate feature name"
assert len(FEATURE_ORDER) == 35, f"expected 35 features, found {len(FEATURE_ORDER)}"
assert set(FEATURE_ORDER) | {"feature_version"} == set(FeatureVector.model_fields), (
    "NUMERIC_FIELDS has drifted from the declared model fields"
)
