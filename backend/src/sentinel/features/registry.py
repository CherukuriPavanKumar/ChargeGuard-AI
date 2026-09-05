"""The versioned feature registry.

An ordered mapping of ``feature name -> extractor callable -> dtype``.  Three
jobs:

1. **Pin the column order.**  LightGBM consumes a positional matrix.  If the
   order drifts between training and serving, every prediction is silently
   wrong -- no exception, no warning, just a broken model.  The registry is the
   single source of truth for that order, and :func:`_assert_consistent` fails
   at import time if it ever diverges from
   :class:`~sentinel.schemas.features.FeatureVector`.

2. **Name the columns.**  Feature-importance output, SHAP-style attributions,
   and audit records all need human-readable names in matrix order.

3. **Type the columns.**  ``int`` features are declared as such so the training
   code can hand LightGBM a correct categorical/integer hint rather than
   treating every column as continuous.

Versioning
----------
``FEATURE_VERSION`` is stamped onto every ``FeatureVector`` and therefore onto
every ``Decision``.  Bump it whenever a feature's *meaning* changes, not merely
when one is added -- a decision made under v1 semantics must remain explicable
under v1 semantics forever.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sentinel.schemas.features import FEATURE_ORDER, FEATURE_VERSION, FeatureVector

#: Re-exported so callers can import version and order from one place.
__all__ = ["FEATURE_VERSION", "FEATURE_ORDER", "REGISTRY", "FeatureSpec",
           "feature_names", "feature_dtypes", "integer_feature_indices",
           "describe_registry"]

DType = Literal["float", "int"]

#: Families used to group features in reports and in the UI.
Family = Literal["transaction", "fulfilment", "behavioural", "evidence"]


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """One column of the model matrix."""

    name: str
    """Field name on :class:`FeatureVector`. Must match exactly."""

    dtype: DType
    """Storage type. ``int`` columns are integer-valued even though the matrix
    itself is float64 -- the hint matters for tree split proposals."""

    family: Family
    """Grouping for reports and the dashboard."""

    extract: Callable[[FeatureVector], float]
    """Pull this column's value out of a built vector. Trivial by construction:
    the builder has already done the work. Present so that consumers can iterate
    the registry uniformly rather than special-casing ``getattr``."""

    description: str
    """One line, mirrored from the schema field description."""


def _getter(name: str) -> Callable[[FeatureVector], float]:
    """Build a positional extractor for ``name``.

    A closure rather than ``operator.attrgetter`` so the returned callable
    coerces to ``float``, guaranteeing the matrix is homogeneous even when the
    underlying field is ``int`` or ``bool``.
    """

    def extract(vector: FeatureVector) -> float:
        return float(getattr(vector, name))

    extract.__name__ = f"extract_{name}"
    extract.__doc__ = f"Return {name} from a FeatureVector as float."
    return extract


def _spec(name: str, dtype: DType, family: Family, description: str) -> FeatureSpec:
    """Construct a spec, binding the extractor automatically."""
    return FeatureSpec(
        name=name,
        dtype=dtype,
        family=family,
        extract=_getter(name),
        description=description,
    )


#: The ordered registry. **This tuple defines the model's column order.**
REGISTRY: tuple[FeatureSpec, ...] = (
    # ------------------------------ transaction ------------------------------
    _spec("amount_inr", "float", "transaction",
          "Disputed amount in rupees; the A_i of the EV rule."),
    _spec("log_amount", "float", "transaction",
          "log(1 + amount); tames the lognormal tail for tree splits."),
    _spec("amount_to_order_ratio", "float", "transaction",
          "Disputed amount / order total; <1 signals a line-item complaint."),
    _spec("window_hours", "float", "transaction",
          "Representment window width, respond_by - disputed_at."),
    _spec("reason_is_fraud", "int", "transaction",
          "1 for VISA_10.4 or MC_4837."),
    _spec("reason_is_non_receipt", "int", "transaction",
          "1 for VISA_13.1 or MC_4853."),
    _spec("reason_is_not_as_described", "int", "transaction",
          "1 for VISA_13.3."),
    _spec("reason_is_credit_not_processed", "int", "transaction",
          "1 for VISA_13.6."),
    _spec("network_is_visa", "int", "transaction",
          "1 for Visa, 0 for Mastercard or RuPay."),
    # ------------------------------ fulfilment -------------------------------
    _spec("pod_present", "int", "fulfilment",
          "1 when a proof-of-delivery parse exists at any trust level."),
    _spec("pod_verified", "int", "fulfilment",
          "1 when extraction_status is VERIFIED."),
    _spec("pod_low_confidence", "int", "fulfilment",
          "1 when extraction_status is LOW_CONFIDENCE."),
    _spec("pod_signature_captured", "int", "fulfilment",
          "1 when a signature glyph was detected."),
    _spec("pod_scan_count", "int", "fulfilment",
          "Carrier network scan events on the shipment."),
    _spec("pod_ocr_confidence", "float", "fulfilment",
          "Mean per-field OCR confidence in [0,1]."),
    _spec("delivery_lag_hours", "float", "fulfilment",
          "Hours from order placement to delivery scan; -1 when illegible."),
    _spec("delivered_before_dispute", "int", "fulfilment",
          "1 when the delivery scan predates the chargeback."),
    _spec("recipient_name_match", "float", "fulfilment",
          "Fuzzy similarity between POD signatory and order customer."),
    _spec("delivery_address_match", "float", "fulfilment",
          "Fuzzy similarity between POD delivery and order shipping address."),
    # ----------------------------- behavioural -------------------------------
    _spec("prior_dispute_count", "int", "behavioural",
          "Prior disputes by this cardholder against this merchant."),
    _spec("account_age_days", "float", "behavioural",
          "Days from account creation to order placement."),
    _spec("login_to_order_minutes", "float", "behavioural",
          "Minutes from session start to order placement."),
    _spec("ip_offshore_distance_km", "float", "behavioural",
          "Great-circle km from checkout IP to the Indian landmass centroid."),
    _spec("ip_is_offshore", "int", "behavioural",
          "1 when the checkout IP is more than 2500 km from India."),
    _spec("user_agent_is_mobile", "int", "behavioural",
          "1 when the checkout User-Agent is a mobile browser."),
    _spec("merchant_comms_count", "int", "behavioural",
          "Logged merchant-to-customer contacts before the dispute."),
    _spec("refund_requested", "int", "behavioural",
          "1 when a refund was requested or issued pre-chargeback."),
    # -------------------------- evidence completeness ------------------------
    _spec("avs_match", "int", "evidence",
          "1 when AVS matched on the authorisation."),
    _spec("cvv_match", "int", "evidence",
          "1 when CVV matched on the authorisation."),
    _spec("three_ds_authenticated", "int", "evidence",
          "1 when 3-D Secure returned AUTHENTICATED."),
    _spec("three_ds_failed", "int", "evidence",
          "1 when 3-D Secure returned FAILED."),
    _spec("liability_shift", "int", "evidence",
          "1 when fraud liability sits with the issuer."),
    _spec("billing_shipping_match", "float", "evidence",
          "Fuzzy similarity between billing and shipping addresses."),
    _spec("item_count", "int", "evidence",
          "Number of line items on the order."),
    _spec("evidence_completeness_score", "float", "evidence",
          "Composite in [0,1] over independent corroborating artifacts."),
)


def feature_names() -> tuple[str, ...]:
    """Column names in matrix order."""
    return tuple(spec.name for spec in REGISTRY)


def feature_dtypes() -> tuple[DType, ...]:
    """Column dtypes in matrix order."""
    return tuple(spec.dtype for spec in REGISTRY)


def integer_feature_indices() -> tuple[int, ...]:
    """Positions of integer-valued columns, for LightGBM's integer hint."""
    return tuple(i for i, spec in enumerate(REGISTRY) if spec.dtype == "int")


def describe_registry() -> list[dict[str, str | int]]:
    """Return a JSON-serialisable description, for API docs and the report."""
    return [
        {
            "index": i,
            "name": spec.name,
            "dtype": spec.dtype,
            "family": spec.family,
            "description": spec.description,
        }
        for i, spec in enumerate(REGISTRY)
    ]


def _assert_consistent() -> None:
    """Fail at import time if the registry has drifted from the schema.

    Three separate ways this can break, all caught here:

    * a field added to ``FeatureVector`` but not registered,
    * a spec registered for a field that no longer exists,
    * the two agreeing on membership but disagreeing on *order*, which is the
      dangerous one because nothing else would notice.
    """
    registry_names = feature_names()
    schema_names = FEATURE_ORDER

    if set(registry_names) != set(schema_names):
        missing = set(schema_names) - set(registry_names)
        extra = set(registry_names) - set(schema_names)
        raise RuntimeError(
            f"feature registry membership drift: "
            f"missing from registry={sorted(missing)}, "
            f"not on FeatureVector={sorted(extra)}"
        )

    if registry_names != schema_names:
        for i, (reg, sch) in enumerate(zip(registry_names, schema_names)):
            if reg != sch:
                raise RuntimeError(
                    f"feature registry order drift at index {i}: "
                    f"registry has {reg!r}, FeatureVector has {sch!r}. "
                    f"Column order must match exactly or the model silently "
                    f"scores the wrong values."
                )

    for spec in REGISTRY:
        if spec.name not in FeatureVector.model_fields:
            raise RuntimeError(f"registered feature {spec.name!r} is not a model field")


_assert_consistent()
