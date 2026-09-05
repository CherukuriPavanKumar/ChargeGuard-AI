"""The pure feature builder.

INVARIANT 2: **this module performs no I/O.**  No network, no disk, no clock
reads, no randomness.  ``build(dispute, bundle)`` is a mathematical function:
the same inputs produce the same output, today and in five years.

``tests/test_feature_purity.py`` enforces this two ways -- it AST-inspects this
file for forbidden imports and forbidden call names, and it calls ``build``
twice on identical inputs and asserts bit-identical output.

Why purity is worth the constraint
----------------------------------
*Train/serve symmetry.*  The training matrix and the serving vector come from
this one function.  If it could read a clock, a feature like "hours since the
dispute" would mean something different at training time than at scoring time,
and the model would learn a relationship that does not hold in production.
This is the single most common way production ML silently degrades, and it is
eliminated here by construction rather than by discipline.

*Reproducibility of decisions.*  An audit record stores the feature snapshot.
Re-running the builder on the archived bundle must reproduce that snapshot
exactly, or the audit trail proves nothing.

*Testability.*  No mocks, no fixtures, no network stubs. Every test is a pure
assertion on values.

The time-derived features
-------------------------
Three features look time-dependent and are not:

* ``window_hours`` is ``respond_by - disputed_at``, both fields *on the event*.
* ``account_age_days`` is ``placed_at - account_created_at``.
* ``login_to_order_minutes`` is ``placed_at - login_at``.

Every one is a difference between two timestamps carried in the input.  The
genuinely clock-dependent question -- "is the filing window still open?" -- is
asked by ``policy.gates.expired_window_gate``, which is allowed to read the
clock because it is policy, not a feature.

``from datetime import timezone`` below imports a *constant*, not a clock; it is
used only to normalise naive timestamps before subtraction.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal

from sentinel.extraction.fuzzy_match import address_similarity, name_similarity
from sentinel.schemas.dispute import DisputeEvent, ReasonCode
from sentinel.schemas.evidence import (
    EvidenceBundle,
    ExtractionStatus,
    ThreeDSStatus,
)
from sentinel.schemas.features import FEATURE_VERSION, FeatureVector

#: Approximate centroid of the Indian landmass (near Nagpur, Maharashtra).
#: A frozen constant, so ``ip_offshore_distance_km`` stays a pure function of
#: its inputs rather than a lookup against a mutable geo database.
INDIA_CENTROID_LAT: float = 21.1458
INDIA_CENTROID_LON: float = 79.0882

#: Distance beyond which a checkout IP is treated as offshore. Chosen to sit
#: outside India's own extent (~3200 km corner to corner, ~1600 km from centroid)
#: so that domestic traffic never trips it.
OFFSHORE_DISTANCE_KM: float = 2500.0

#: Mean Earth radius, kilometres.
_EARTH_RADIUS_KM: float = 6371.0088

#: Sentinel for "no legible delivery timestamp". Negative so tree splits can
#: isolate it cleanly from any real lag, which is always non-negative.
NO_DELIVERY_SENTINEL: float = -1.0

#: Saturation points for the completeness composite.
_SCAN_SATURATION: float = 6.0
_COMMS_SATURATION: float = 3.0


def _as_utc(moment: datetime) -> datetime:
    """Attach UTC to a naive timestamp so subtraction is well-defined.

    Reads no clock: ``timezone.utc`` is a constant offset object.
    """
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _hours_between(start: datetime, end: datetime) -> float:
    """Signed hours from ``start`` to ``end``."""
    return (_as_utc(end) - _as_utc(start)).total_seconds() / 3600.0


def _minutes_between(start: datetime, end: datetime) -> float:
    """Signed minutes from ``start`` to ``end``."""
    return (_as_utc(end) - _as_utc(start)).total_seconds() / 60.0


def _days_between(start: datetime, end: datetime) -> float:
    """Signed days from ``start`` to ``end``."""
    return (_as_utc(end) - _as_utc(start)).total_seconds() / 86400.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two WGS-84 points.

    Implemented inline rather than pulled from a geo library because the whole
    dependency would be one formula, and a pure local implementation keeps
    INVARIANT 2 trivially auditable.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, a)))


def _saturate(value: float, ceiling: float) -> float:
    """Map ``[0, ceiling]`` onto ``[0, 1]``, clamping above.

    Used for count features in the completeness composite: the difference
    between two scans and six matters; the difference between twelve and twenty
    does not.
    """
    if ceiling <= 0:
        return 0.0
    return min(1.0, max(0.0, value / ceiling))


def _completeness(
    pod_present: bool,
    pod_verified: bool,
    signature: bool,
    scan_count: int,
    name_match: float,
    address_match: float,
    avs: bool,
    cvv: bool,
    three_ds_auth: bool,
    comms_count: int,
) -> float:
    """Composite in [0, 1] over ten independent corroborating artifacts.

    An unweighted mean, deliberately.  A learned weighting would duplicate what
    the gradient-boosted model already does, and would make this feature a
    second, unaudited model embedded inside the feature layer.  Its purpose is
    to give the tree a single low-variance summary of "how much paper do we
    hold", not to predict anything on its own.

    This is **not** a probability and is never treated as one.
    """
    components = (
        1.0 if pod_present else 0.0,
        1.0 if pod_verified else 0.0,
        1.0 if signature else 0.0,
        _saturate(float(scan_count), _SCAN_SATURATION),
        max(0.0, min(1.0, name_match)),
        max(0.0, min(1.0, address_match)),
        1.0 if avs else 0.0,
        1.0 if cvv else 0.0,
        1.0 if three_ds_auth else 0.0,
        _saturate(float(comms_count), _COMMS_SATURATION),
    )
    return sum(components) / len(components)


def build(dispute: DisputeEvent, bundle: EvidenceBundle) -> FeatureVector:
    """Build the 35-dimensional feature vector for one dispute.

    Pure. Deterministic. No I/O.

    Args:
        dispute: The inbound chargeback event.
        bundle: All evidence held for it, across all three modalities.

    Returns:
        A frozen :class:`FeatureVector` stamped with ``FEATURE_VERSION``.
    """
    pod = bundle.pod
    order = bundle.order
    session = bundle.session

    # ------------------------------------------------------------------ #
    # TRANSACTION                                                        #
    # ------------------------------------------------------------------ #
    amount = float(dispute.amount_inr)
    order_total = float(order.order_total)
    # Guard against a zero total even though the schema forbids it: a defensive
    # divide here is cheaper than an unhandled ZeroDivisionError in serving.
    amount_ratio = amount / order_total if order_total > 0.0 else 1.0

    reason = dispute.reason_code
    window = dispute.window_hours

    # ------------------------------------------------------------------ #
    # FULFILMENT                                                         #
    # ------------------------------------------------------------------ #
    status = pod.extraction_status
    pod_present = status is not ExtractionStatus.ABSENT
    pod_verified = status is ExtractionStatus.VERIFIED
    pod_low_conf = status is ExtractionStatus.LOW_CONFIDENCE

    if pod.delivered_at is None:
        delivery_lag = NO_DELIVERY_SENTINEL
        delivered_before_dispute = 0
    else:
        delivery_lag = _hours_between(order.placed_at, pod.delivered_at)
        delivered_before_dispute = int(
            _as_utc(pod.delivered_at) < _as_utc(dispute.disputed_at)
        )

    name_match = name_similarity(pod.recipient_name, order.customer_name)
    address_match = address_similarity(pod.delivery_address, order.shipping_address)

    # ------------------------------------------------------------------ #
    # BEHAVIOURAL                                                        #
    # ------------------------------------------------------------------ #
    account_age = _days_between(session.account_created_at, order.placed_at)
    login_to_order = _minutes_between(session.login_at, order.placed_at)

    offshore_km = haversine_km(
        session.ip_geo_lat,
        session.ip_geo_lon,
        INDIA_CENTROID_LAT,
        INDIA_CENTROID_LON,
    )

    # ------------------------------------------------------------------ #
    # EVIDENCE COMPLETENESS                                              #
    # ------------------------------------------------------------------ #
    three_ds = order.three_ds_status
    three_ds_auth = three_ds is ThreeDSStatus.AUTHENTICATED
    billing_shipping = address_similarity(order.billing_address, order.shipping_address)

    completeness = _completeness(
        pod_present=pod_present,
        pod_verified=pod_verified,
        signature=pod.signature_captured,
        scan_count=pod.scan_count,
        name_match=name_match,
        address_match=address_match,
        avs=order.avs_match,
        cvv=order.cvv_match,
        three_ds_auth=three_ds_auth,
        comms_count=bundle.merchant_comms_count,
    )

    return FeatureVector(
        feature_version=FEATURE_VERSION,
        # ---- transaction ----
        amount_inr=amount,
        log_amount=math.log1p(amount),
        amount_to_order_ratio=amount_ratio,
        window_hours=window,
        reason_is_fraud=int(dispute.is_fraud_code),
        reason_is_non_receipt=int(dispute.is_non_receipt_code),
        reason_is_not_as_described=int(reason is ReasonCode.VISA_13_3),
        reason_is_credit_not_processed=int(reason is ReasonCode.VISA_13_6),
        network_is_visa=int(dispute.network.value == "VISA"),
        # ---- fulfilment ----
        pod_present=int(pod_present),
        pod_verified=int(pod_verified),
        pod_low_confidence=int(pod_low_conf),
        pod_signature_captured=int(pod.signature_captured),
        pod_scan_count=pod.scan_count,
        pod_ocr_confidence=pod.ocr_confidence,
        delivery_lag_hours=delivery_lag,
        delivered_before_dispute=delivered_before_dispute,
        recipient_name_match=name_match,
        delivery_address_match=address_match,
        # ---- behavioural ----
        prior_dispute_count=bundle.prior_dispute_count,
        account_age_days=account_age,
        login_to_order_minutes=login_to_order,
        ip_offshore_distance_km=offshore_km,
        ip_is_offshore=int(offshore_km > OFFSHORE_DISTANCE_KM),
        user_agent_is_mobile=int(session.is_mobile),
        merchant_comms_count=bundle.merchant_comms_count,
        refund_requested=int(bundle.refund_requested),
        # ---- evidence completeness ----
        avs_match=int(order.avs_match),
        cvv_match=int(order.cvv_match),
        three_ds_authenticated=int(three_ds_auth),
        three_ds_failed=int(three_ds is ThreeDSStatus.FAILED),
        liability_shift=int(order.liability_shifted),
        billing_shipping_match=billing_shipping,
        item_count=len(order.items),
        evidence_completeness_score=completeness,
    )


def build_matrix(
    pairs: list[tuple[DisputeEvent, EvidenceBundle]],
) -> tuple[list[FeatureVector], list[Decimal]]:
    """Build vectors for many disputes, returning vectors and amounts.

    The amounts are returned alongside because every downstream economic
    computation needs ``A_i`` as an exact :class:`Decimal`, and the feature
    vector deliberately holds it only as a lossy float.
    """
    vectors: list[FeatureVector] = []
    amounts: list[Decimal] = []
    for dispute, bundle in pairs:
        vectors.append(build(dispute, bundle))
        amounts.append(dispute.amount_inr)
    return vectors, amounts
