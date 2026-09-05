r"""Synthetic dispute corpus with an explicit latent winnability process.

Read this module before believing any metric in ``eval/reports/REPORT.md``.
There is no real chargeback data here.  Every number the harness reports is a
statement about *this* generative process, and the honest way to present such a
result is to make the process legible enough that a reader can judge whether it
was rigged.

The data-generating process
===========================

For each dispute we sample a set of **latent** variables the model never sees,
compute a latent winnability score, convert it to a probability, and sample the
realised binary outcome.  Only *noisy observations* of the latent drivers are
written into the evidence bundle.

Step 1 -- latent variables
--------------------------

``is_friendly_fraud``
    The cardholder is lying: the goods arrived, or the transaction was
    authorised, and they are disputing anyway.  This is the single largest
    driver of whether a representment succeeds, and it is **completely
    unobservable**.  No feature encodes it.

``true_evidence_quality`` (q, in [0,1])
    How good the merchant's paper trail actually is, before any extraction loss.

``actually_delivered``
    Whether the parcel physically reached the address.

``address_consistency`` (a, in [0,1])
    How well billing, shipping, and delivery addresses genuinely agree.

Step 2 -- the latent score
--------------------------

.. code-block:: text

    z = b0
      + b_ff   * is_friendly_fraud
      + b_ev   * (q - 0.5)
      + b_rc[reason_code]
      + b_ls   * liability_shift
      + b_ad   * (a - 0.5)
      + b_pr   * min(prior_disputes, 6)
      + b_pnr  * [non_receipt AND actually_delivered AND pod_exists]
      + b_fls  * [fraud_code AND liability_shift]
      + b_nls  * [fraud_code AND NOT liability_shift]
      + b_npod * [non_receipt AND NOT pod_exists]
      + b_rf   * [credit_not_processed AND refund_issued]
      + eps,     eps ~ Normal(0, sigma)

Step 3 -- outcome
-----------------

``p_true = sigmoid(z)``, then ``w ~ Bernoulli(p_true)``, then a label flip with
probability :data:`LABEL_NOISE_RATE` representing issuer arbitrariness -- two
identical filings genuinely do not always land the same way.

One outcome is *not* sampled: a dispute whose representment window has already
closed is forced to ``w = 0``.  A filing that cannot be submitted cannot
succeed, and leaving those labels stochastic would credit every deadline-blind
policy with recoveries that were never reachable.

Where the generator and the policy gates agree
----------------------------------------------

Three of the interaction terms -- ``b_nls``, ``b_npod`` and ``b_rf`` -- have a
one-to-one correspondence with policy gates in :mod:`sentinel.policy.gates`.
This is not circularity.  Both sides are independent expressions of the same
card-scheme rulebook: the gate says "we will not file this", and the coefficient
says "filings like this do not succeed".  They are stated separately, in
different modules, and they *must* agree or one of them is wrong about the
world.

An earlier revision of this generator omitted ``b_nls`` and ``b_npod``.  The
harness then reported a 25% win rate inside the segment that
``fraud_without_liability_shift_gate`` forces to ACCEPT, which made the gate
look value-destroying.  The gate was right and the world model was wrong; see
section 3 of ``eval/reports/REPORT.md`` for the corrected figures.

Step 4 -- observation
---------------------

The observables are degraded views of the latent:

* the POD document exists only sometimes, and when it exists OCR recovers it
  imperfectly, with confidence driven by carrier print quality and physical
  damage;
* the recipient name on the slip is a truncation, an initialisation, a
  relative's name, or garbage, with fidelity falling as ``q`` falls;
* addresses are reformatted and abbreviated;
* a slice of otherwise-good documents is simply lost (:data:`POD_LOST_RATE`) or
  fails extraction outright (:data:`POD_EXTRACTION_FAILURE_RATE`).

Why the achievable AUC is bounded
=================================

``is_friendly_fraud`` carries a coefficient of |b_ff| and appears in **no
feature**.  Neither does ``eps``.  Together they place a hard ceiling on any
classifier: even a model that recovered ``q``, ``a`` and every interaction
perfectly would still face irreducible Bayes error from those two terms.

This is deliberate and it is the honest choice.  A generator whose features
determined the label would produce an AUC near 1.0 and prove nothing except
that the author wrote both sides of the exam.  The interesting question this
codebase asks is not "can a model separate the classes" but "given a genuinely
uncertain, well-calibrated probability, does the economic policy layer extract
most of the available money?"  That is what ``oracle_efficiency`` measures, and
it is a meaningful question precisely because the AUC is bounded well below 1.

Determinism
===========

Every draw comes from a seeded stream in :mod:`data_gen.seeds`.  Timestamps are
offsets from the frozen :data:`~data_gen.seeds.CORPUS_EPOCH` and are rebased by
a rigid translation at load time; see that module for why this preserves both
reproducibility and the meaning of ``expired_window_gate``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np

from data_gen import distributions as dist
from data_gen.seeds import (
    CORPUS_EPOCH,
    DISPUTE_SEED,
    MASTER_SEED,
    EXPIRED_FRACTION,
    IDENTITY_SEED,
    LATENT_SEED,
    OBSERVATION_SEED,
    SPLIT_SEED,
)
from sentinel.schemas.dispute import DisputeEvent, ReasonCode
from sentinel.schemas.evidence import (
    Carrier,
    EvidenceBundle,
    ExtractionStatus,
    OrderRecord,
    ProofOfDelivery,
    SessionLog,
    ThreeDSStatus,
)

# --------------------------------------------------------------------------- #
# Latent coefficients                                                         #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LatentCoefficients:
    """Coefficients of the latent winnability score.

    The intercept is calibrated so the realised corpus win rate lands at
    **44.5%**, inside the 20-45% band that industry reporting gives for merchant
    representment outcomes on friendly-fraud-heavy volume.  Every other
    coefficient is a modelling assumption chosen for the *shape* of the decision
    problem, not tuned against any metric the harness reports.
    """

    intercept: float = -2.35
    """b0. Sets the base rate; negative because most chargebacks stand."""

    friendly_fraud: float = 1.55
    """b_ff. The dominant driver, and completely unobservable. This coefficient
    is the main reason the achievable AUC is bounded."""

    evidence_quality: float = 2.40
    """b_ev, applied to (q - 0.5). Observable only through OCR, so the model
    sees a noise-corrupted version."""

    liability_shift: float = 1.30
    """b_ls. Fully observable via three_ds_status -- the model should learn this
    cleanly, and it does."""

    address_consistency: float = 1.10
    """b_ad, applied to (a - 0.5)."""

    prior_disputes: float = 0.10
    """b_pr, per prior dispute up to six. Recidivism correlates with friendly
    fraud, so it is a weak proxy for the unobservable term."""

    pod_on_non_receipt: float = 1.25
    """b_pnr. Interaction: a real delivery with a real POD, on a code where POD
    is the decisive artifact."""

    fraud_with_liability_shift: float = 0.85
    """b_fls. Interaction: 3-D Secure on a fraud denial is close to dispositive."""

    refund_on_credit_code: float = -3.40
    """b_rf. Interaction: the cardholder's allegation is true. Near-fatal."""

    fraud_without_liability_shift: float = -1.70
    """b_nls. Interaction: a fraud denial with no 3-D Secure liability shift.

    Large and negative because that is what the rulebook does. Under Visa 10.4
    and Mastercard 4837 the merchant retains fraud liability absent an
    authenticated 3-D Secure result, and issuers uphold these disputes at very
    high rates -- published merchant win rates sit in the 5-10% band. Combined
    with the -0.95 main effect this drives the segment to roughly 6%.

    This coefficient exists because ``fraud_without_liability_shift_gate``
    asserts the same fact on the policy side. The two agree because both
    describe the same card-scheme rulebook, not because one was fitted to the
    other -- and an earlier version of this generator that omitted the term
    produced a 25% win rate in the gated segment, which made the gate look
    value-destroying when in fact the world model was wrong."""

    non_receipt_without_pod: float = -2.15
    """b_npod. Interaction: a not-received claim with no proof of delivery.

    Under Visa 13.1 proof of delivery is the compelling evidence the scheme
    requires. With no document at all there is nothing to file; the residual
    win rate reflects the occasional case carried by prior undisputed
    transaction history. Mirrors ``no_pod_on_non_receipt_gate``."""

    noise_sigma: float = 0.85
    """sigma of eps. The second unobservable term."""


#: Reason-code main effects, ``b_rc``.
REASON_EFFECT: dict[ReasonCode, float] = {
    ReasonCode.VISA_13_1: 0.10,
    ReasonCode.MC_4853: 0.00,
    ReasonCode.VISA_13_3: -0.45,
    ReasonCode.VISA_10_4: -0.95,
    ReasonCode.MC_4837: -0.90,
    ReasonCode.VISA_13_6: 0.35,
}

#: Probability the cardholder's claim is illegitimate. This is the loss vector
#: ChargeGuard exists to defend against.
FRIENDLY_FRAUD_RATE: float = 0.62

#: Issuer arbitrariness: identical filings do not always land the same way.
LABEL_NOISE_RATE: float = 0.03

#: A POD document that was created but never made it into the evidence bundle.
POD_LOST_RATE: float = 0.08

#: A POD document present but unreadable -- the ``UNVERIFIED`` path.
POD_EXTRACTION_FAILURE_RATE: float = 0.05

#: Share of friendly-fraud disputes belonging to a coordinated ring, which share
#: device fingerprints from a small pool.
FRAUD_RING_SHARE: float = 0.04

#: Size of the shared device pool used by rings.
FRAUD_RING_DEVICE_POOL: int = 12

COEFFS = LatentCoefficients()


def _sigmoid(x: float) -> float:
    """Numerically stable logistic function."""
    if x >= 0:
        return float(1.0 / (1.0 + np.exp(-x)))
    e = float(np.exp(x))
    return e / (1.0 + e)


# --------------------------------------------------------------------------- #
# Corpus record                                                               #
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class CorpusRecord:
    """One generated dispute: inputs, outcome, and latent diagnostics.

    ``latent`` is written to disk under a leading-underscore key and is stripped
    by :func:`load_corpus` before anything downstream sees it.  It exists only
    so the report can show the generative process was what it claims to be.
    """

    dispute: DisputeEvent
    bundle: EvidenceBundle
    won: int
    """Realised outcome w_i: 1 if a representment would have succeeded."""

    split: str
    """``"train"`` or ``"test"``."""

    pod_image_path: str | None = None
    """Set for the subset of records whose POD slip is rendered to disk."""

    latent: dict[str, float] = field(default_factory=dict)
    """Diagnostics only. Never reaches the feature builder."""


# --------------------------------------------------------------------------- #
# Identity synthesis                                                          #
# --------------------------------------------------------------------------- #


def _full_name(rng: np.random.Generator) -> str:
    """Draw a plausible Indian full name."""
    first = dist.FIRST_NAMES[int(rng.integers(0, len(dist.FIRST_NAMES)))]
    last = dist.LAST_NAMES[int(rng.integers(0, len(dist.LAST_NAMES)))]
    return f"{first} {last}"


def _address(rng: np.random.Generator, city_rec: tuple) -> str:
    """Compose a structured Indian postal address for a given metro."""
    city, state, _lat, _lon, pin_prefix = city_rec
    flat = int(rng.integers(101, 1204))
    building = dist.BUILDING_NAMES[int(rng.integers(0, len(dist.BUILDING_NAMES)))]
    street = dist.STREET_NAMES[int(rng.integers(0, len(dist.STREET_NAMES)))]
    pincode = f"{pin_prefix}{int(rng.integers(1, 100)):03d}"
    return f"Flat {flat}, {building}, {street}, {city}, {state} {pincode}"


def _abbreviate_address(rng: np.random.Generator, address: str, fidelity: float) -> str:
    """Return the carrier's rendering of an address at a given fidelity.

    Couriers re-key addresses into their own systems, dropping the building
    name, abbreviating directions, and occasionally losing the state.  Fidelity
    controls how much survives.
    """
    parts = [p.strip() for p in address.split(",")]
    if fidelity > 0.85:
        return address
    if fidelity > 0.62:
        # Drop the building name; keep flat, street, city, state+pin.
        kept = [parts[0]] + parts[2:]
        return ", ".join(kept)
    if fidelity > 0.38:
        # Keep only street, city and postal code.
        tail = parts[-1]
        return f"{parts[2]}, {tail}" if len(parts) > 3 else tail
    if fidelity > 0.18:
        # Postal code and city only -- still enough for a pincode match.
        return parts[-1]
    return ""


def _degrade_name(rng: np.random.Generator, name: str, fidelity: float) -> str:
    """Return the recipient name as the courier recorded it.

    Four regimes, in falling fidelity: verbatim, initialised surname, a
    household member who signed instead, and unrecoverable.
    """
    first, _, last = name.partition(" ")
    roll = float(rng.random())

    if roll < fidelity * 0.88:
        return name
    if roll < fidelity * 0.88 + 0.09:
        return f"{first} {last[:1]}." if last else first
    if roll < fidelity * 0.88 + 0.15:
        # A relative signed: same surname, different given name.
        other = dist.FIRST_NAMES[int(rng.integers(0, len(dist.FIRST_NAMES)))]
        return f"{other} {last}" if last else other
    if roll < fidelity * 0.88 + 0.19:
        return "SELF"
    return ""


def _device_fingerprint(rng: np.random.Generator, ring_slot: int | None) -> str:
    """Return a device hash, shared within a ring or unique otherwise."""
    if ring_slot is not None:
        return f"dev_ring_{ring_slot:02d}_" + hashlib.sha1(
            f"ring{ring_slot}".encode()
        ).hexdigest()[:12]
    raw = f"{int(rng.integers(0, 2**62))}"
    return "dev_" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def _ip_address(rng: np.random.Generator) -> str:
    """Draw a plausible public IPv4 string."""
    return ".".join(str(int(rng.integers(1, 254))) for _ in range(4))


def _pick_items(
    rng: np.random.Generator, order_total: float
) -> tuple[str, ...]:
    """Choose 1-4 catalogue labels whose price band suits the order total.

    Labels are chosen by proximity to ``order_total / n``, so a INR 30 000 order
    shows monitors and headphones rather than a yoga mat.  The authoritative
    total remains ``order_total``; the labels are descriptive.
    """
    n_items = int(rng.integers(1, 5))
    target = order_total / n_items
    prices = np.array([p for _, p in dist.ITEM_CATALOGUE], dtype=np.float64)
    # Rank catalogue entries by log-distance to the target price, then sample
    # from the closest third so labels vary between orders of similar value.
    order = np.argsort(np.abs(np.log(prices) - np.log(max(target, 1.0))))
    pool = order[: max(4, len(order) // 3)]
    chosen = rng.choice(pool, size=n_items, replace=True)
    return tuple(dist.ITEM_CATALOGUE[int(i)][0] for i in chosen)


# --------------------------------------------------------------------------- #
# The generator                                                               #
# --------------------------------------------------------------------------- #


def _generate_one(
    index: int,
    rng_dispute: np.random.Generator,
    rng_latent: np.random.Generator,
    rng_obs: np.random.Generator,
    rng_id: np.random.Generator,
    reason_code: ReasonCode,
    amount: float,
    is_expired: bool,
) -> CorpusRecord:
    """Generate one dispute end to end.

    The order of operations mirrors the module docstring: latent variables
    first, then the score and outcome, then the observation layer.
    """
    # ------------------------------------------------------------------ #
    # LATENT (never observed)                                            #
    # ------------------------------------------------------------------ #
    is_friendly_fraud = bool(rng_latent.random() < FRIENDLY_FRAUD_RATE)

    # Evidence quality: friendly-fraud cases skew toward a good paper trail,
    # because the merchant really did ship and really does hold the documents.
    if is_friendly_fraud:
        true_evidence_quality = float(rng_latent.beta(4.2, 2.0))
    else:
        true_evidence_quality = float(rng_latent.beta(2.0, 3.4))

    is_non_receipt = reason_code in (ReasonCode.VISA_13_1, ReasonCode.MC_4853)
    is_fraud_code = reason_code in (ReasonCode.VISA_10_4, ReasonCode.MC_4837)
    is_credit_code = reason_code is ReasonCode.VISA_13_6

    if is_credit_code:
        # Digital or subscription goods: usually nothing was shipped at all.
        actually_delivered = bool(rng_latent.random() < 0.15)
    elif is_friendly_fraud:
        actually_delivered = bool(rng_latent.random() < 0.88)
    else:
        actually_delivered = bool(rng_latent.random() < 0.34)

    address_consistency = float(rng_latent.beta(5.0, 1.8))

    # ------------------------------------------------------------------ #
    # ORDER AND SESSION                                                  #
    # ------------------------------------------------------------------ #
    three_ds = dist.sample_three_ds(rng_dispute, amount)
    liability_shift = three_ds is ThreeDSStatus.AUTHENTICATED

    # Partial disputes: the cardholder challenges part of a larger order.
    if rng_dispute.random() < 0.78:
        ratio = 1.0
    else:
        ratio = float(rng_dispute.uniform(0.35, 0.95))
    order_total = round(amount / ratio, 2)

    customer_name = _full_name(rng_id)
    city_rec = dist.sample_city(rng_id)
    shipping_address = _address(rng_id, city_rec)

    # Billing usually equals shipping; divergence is partly gifting, partly fraud.
    same_address_prob = 0.88 if address_consistency > 0.5 else 0.55
    if rng_id.random() < same_address_prob:
        billing_address = shipping_address
    else:
        billing_address = _address(rng_id, dist.sample_city(rng_id))

    avs_match = bool(
        rng_dispute.random() < (0.90 if billing_address == shipping_address else 0.42)
    )
    cvv_match = bool(rng_dispute.random() < 0.93)

    # ------------------------------------------------------------------ #
    # TIMESTAMPS -- all offsets from the frozen anchor                   #
    # ------------------------------------------------------------------ #
    if is_expired:
        hours_remaining = -float(
            rng_dispute.uniform(*dist.EXPIRED_HOURS_OVERDUE_RANGE)
        )
    else:
        hours_remaining = float(rng_dispute.uniform(*dist.LIVE_HOURS_REMAINING_RANGE))

    window_hours = float(rng_dispute.uniform(*dist.WINDOW_HOURS_RANGE))
    respond_by = CORPUS_EPOCH + timedelta(hours=hours_remaining)
    disputed_at = respond_by - timedelta(hours=window_hours)

    dispute_lag_days = float(rng_dispute.uniform(*dist.DISPUTE_LAG_DAYS_RANGE))
    placed_at = disputed_at - timedelta(days=dispute_lag_days)

    fresh_prob = (
        dist.FRESH_ACCOUNT_PROB_FRAUD
        if is_friendly_fraud
        else dist.FRESH_ACCOUNT_PROB_GENUINE
    )
    if rng_id.random() < fresh_prob:
        account_age_days = float(rng_id.uniform(*dist.ACCOUNT_AGE_FRESH_RANGE))
    else:
        account_age_days = float(rng_id.uniform(*dist.ACCOUNT_AGE_ESTABLISHED_RANGE))
    account_created_at = placed_at - timedelta(days=account_age_days)

    scripted_prob = (
        dist.SCRIPTED_CHECKOUT_PROB_FRAUD
        if is_friendly_fraud
        else dist.SCRIPTED_CHECKOUT_PROB_GENUINE
    )
    if rng_id.random() < scripted_prob:
        login_minutes = float(rng_id.uniform(*dist.LOGIN_TO_ORDER_SCRIPTED_RANGE))
    else:
        login_minutes = float(rng_id.uniform(*dist.LOGIN_TO_ORDER_HUMAN_RANGE))
    login_at = placed_at - timedelta(minutes=login_minutes)

    # ------------------------------------------------------------------ #
    # SESSION TELEMETRY                                                  #
    # ------------------------------------------------------------------ #
    offshore_prob = (
        dist.OFFSHORE_PROB_FRAUD if is_friendly_fraud else dist.OFFSHORE_PROB_GENUINE
    )
    if rng_id.random() < offshore_prob:
        lat, lon = dist.OFFSHORE_COORDS[
            int(rng_id.integers(0, len(dist.OFFSHORE_COORDS)))
        ]
        ip_lat, ip_lon = dist.jitter_coords(rng_id, lat, lon, spread_deg=0.4)
    else:
        ip_lat, ip_lon = dist.jitter_coords(rng_id, city_rec[2], city_rec[3])

    ring_slot: int | None = None
    if is_friendly_fraud and rng_id.random() < FRAUD_RING_SHARE:
        ring_slot = int(rng_id.integers(0, FRAUD_RING_DEVICE_POOL))

    if rng_id.random() < dist.MOBILE_SHARE:
        user_agent = dist.USER_AGENTS_MOBILE[
            int(rng_id.integers(0, len(dist.USER_AGENTS_MOBILE)))
        ]
    else:
        user_agent = dist.USER_AGENTS_DESKTOP[
            int(rng_id.integers(0, len(dist.USER_AGENTS_DESKTOP)))
        ]

    session = SessionLog(
        ip_address=_ip_address(rng_id),
        ip_geo_lat=float(np.clip(ip_lat, -90.0, 90.0)),
        ip_geo_lon=float(np.clip(ip_lon, -180.0, 180.0)),
        device_fingerprint=_device_fingerprint(rng_id, ring_slot),
        user_agent=user_agent,
        login_at=login_at,
        account_created_at=account_created_at,
    )

    # ------------------------------------------------------------------ #
    # OBSERVATION LAYER -- the POD                                       #
    # ------------------------------------------------------------------ #
    carrier = dist.sample_carrier(rng_obs)

    if is_credit_code:
        pod_exists_prob = 0.15
    elif actually_delivered:
        pod_exists_prob = 0.88
    else:
        pod_exists_prob = 0.12
    pod_document_exists = bool(rng_obs.random() < pod_exists_prob)

    # A created document that never reached the evidence bundle.
    if pod_document_exists and rng_obs.random() < POD_LOST_RATE:
        pod_document_exists = False

    if not pod_document_exists:
        pod = ProofOfDelivery(extraction_status=ExtractionStatus.ABSENT)
        observed_ocr_conf = 0.0
    elif rng_obs.random() < POD_EXTRACTION_FAILURE_RATE:
        # Present but unreadable: the UNVERIFIED path, distinct from ABSENT.
        pod = ProofOfDelivery(
            carrier=carrier,
            extraction_status=ExtractionStatus.UNVERIFIED,
            ocr_confidence=0.0,
        )
        observed_ocr_conf = 0.0
    else:
        print_quality = dist.CARRIER_PRINT_QUALITY[carrier]
        clean_conf = print_quality * (0.55 + 0.45 * true_evidence_quality)
        damage = float(rng_obs.normal(0.0, 0.11))
        observed_ocr_conf = float(np.clip(clean_conf + damage, 0.05, 0.99))

        fidelity = float(np.clip(0.5 * observed_ocr_conf + 0.5 * true_evidence_quality,
                                 0.0, 1.0))
        recipient = _degrade_name(rng_obs, customer_name, fidelity)
        delivery_address = _abbreviate_address(rng_obs, shipping_address, fidelity)

        signature = bool(rng_obs.random() < (0.15 + 0.80 * true_evidence_quality))
        scan_count = dist.sample_scan_count(rng_obs, carrier)

        if actually_delivered:
            delivery_lag = float(rng_obs.uniform(*dist.DELIVERY_LAG_HOURS_RANGE))
            delivered_at: datetime | None = placed_at + timedelta(hours=delivery_lag)
        else:
            delivered_at = None

        # Heavy damage can also destroy the timestamp specifically.
        if delivered_at is not None and observed_ocr_conf < 0.35:
            if rng_obs.random() < 0.45:
                delivered_at = None

        decisive_present = bool(recipient) and bool(delivery_address)
        if observed_ocr_conf >= 0.55 and decisive_present:
            status = ExtractionStatus.VERIFIED
        else:
            status = ExtractionStatus.LOW_CONFIDENCE

        pod = ProofOfDelivery(
            awb_number=f"{carrier.value[:3]}{int(rng_obs.integers(10**9, 10**10))}",
            delivered_at=delivered_at,
            recipient_name=recipient,
            signature_captured=signature,
            delivery_address=delivery_address,
            carrier=carrier,
            scan_count=scan_count,
            ocr_confidence=round(observed_ocr_conf, 4),
            extraction_status=status,
        )

    # ------------------------------------------------------------------ #
    # BEHAVIOURAL COUNTS                                                 #
    # ------------------------------------------------------------------ #
    prior_lambda = 1.6 if is_friendly_fraud else 0.35
    prior_dispute_count = int(np.clip(rng_obs.poisson(prior_lambda), 0, 8))
    merchant_comms_count = int(
        np.clip(rng_obs.poisson(0.8 + 2.2 * true_evidence_quality), 0, 9)
    )

    if is_credit_code:
        refund_requested = bool(rng_obs.random() < 0.55)
    else:
        refund_requested = bool(rng_obs.random() < 0.12)

    order = OrderRecord(
        order_id=f"ord_{index:06d}",
        customer_name=customer_name,
        billing_address=billing_address,
        shipping_address=shipping_address,
        placed_at=placed_at,
        items=_pick_items(rng_id, order_total),
        order_total=Decimal(str(order_total)),
        avs_match=avs_match,
        cvv_match=cvv_match,
        three_ds_status=three_ds,
    )

    bundle = EvidenceBundle(
        pod=pod,
        order=order,
        session=session,
        prior_dispute_count=prior_dispute_count,
        refund_requested=refund_requested,
        merchant_comms_count=merchant_comms_count,
    )

    # ------------------------------------------------------------------ #
    # LATENT SCORE AND OUTCOME                                           #
    # ------------------------------------------------------------------ #
    z = COEFFS.intercept
    z += COEFFS.friendly_fraud * float(is_friendly_fraud)
    z += COEFFS.evidence_quality * (true_evidence_quality - 0.5)
    z += REASON_EFFECT[reason_code]
    z += COEFFS.liability_shift * float(liability_shift)
    z += COEFFS.address_consistency * (address_consistency - 0.5)
    z += COEFFS.prior_disputes * min(prior_dispute_count, 6)

    if is_non_receipt and actually_delivered and pod_document_exists:
        z += COEFFS.pod_on_non_receipt
    if is_fraud_code and liability_shift:
        z += COEFFS.fraud_with_liability_shift
    if is_fraud_code and not liability_shift:
        z += COEFFS.fraud_without_liability_shift
    if is_non_receipt and not pod_document_exists:
        z += COEFFS.non_receipt_without_pod
    if is_credit_code and refund_requested:
        z += COEFFS.refund_on_credit_code

    z += float(rng_latent.normal(0.0, COEFFS.noise_sigma))

    p_true = _sigmoid(z)
    won = int(rng_latent.random() < p_true)

    # Issuer arbitrariness: the same filing does not always land the same way.
    if rng_latent.random() < LABEL_NOISE_RATE:
        won = 1 - won

    # A representment that cannot be filed cannot be won. Once the scheme window
    # has closed the outcome is deterministic, so the label is forced rather than
    # sampled. Without this the corpus contains disputes labelled winnable that
    # no filing could ever have reached, and every policy that ignores the
    # deadline is credited with recoveries that were never available.
    if is_expired:
        won = 0

    network = dist.network_for_reason(rng_dispute, reason_code)

    dispute = DisputeEvent(
        dispute_id=f"dp_{index:06d}",
        transaction_id=f"txn_{index:06d}",
        merchant_id=f"acc_{int(rng_dispute.integers(1, 40)):04d}",
        reason_code=reason_code,
        amount_inr=Decimal(str(amount)),
        currency="INR",
        disputed_at=disputed_at,
        respond_by=respond_by,
        network=network,
    )

    return CorpusRecord(
        dispute=dispute,
        bundle=bundle,
        won=won,
        split="",
        latent={
            "is_friendly_fraud": float(is_friendly_fraud),
            "true_evidence_quality": round(true_evidence_quality, 5),
            "actually_delivered": float(actually_delivered),
            "address_consistency": round(address_consistency, 5),
            "latent_score": round(z, 5),
            "p_true": round(p_true, 5),
        },
    )


def generate_corpus(
    n_total: int, n_train: int, n_test: int
) -> list[CorpusRecord]:
    """Generate the full corpus and assign the frozen train/test split.

    Args:
        n_total: Total disputes to generate.
        n_train: Rows assigned to the training split.
        n_test: Rows assigned to the held-out test split.

    Returns:
        Records in generation order, each tagged with its split.

    Raises:
        ValueError: if the splits do not sum to the total.
    """
    if n_train + n_test != n_total:
        raise ValueError(
            f"split sizes must sum to the total: {n_train} + {n_test} != {n_total}"
        )

    rng_dispute = np.random.default_rng(DISPUTE_SEED)
    rng_latent = np.random.default_rng(LATENT_SEED)
    rng_obs = np.random.default_rng(OBSERVATION_SEED)
    rng_id = np.random.default_rng(IDENTITY_SEED)

    reason_codes = dist.sample_reason_codes(rng_dispute, n_total)
    amounts = dist.sample_amounts(rng_dispute, reason_codes)

    # Fix the expired set up front so its size is exactly EXPIRED_FRACTION and
    # does not drift with the timestamp distribution.
    n_expired = int(round(EXPIRED_FRACTION * n_total))
    expired_idx = set(
        int(i) for i in rng_dispute.choice(n_total, size=n_expired, replace=False)
    )

    records: list[CorpusRecord] = []
    for i in range(n_total):
        records.append(
            _generate_one(
                index=i,
                rng_dispute=rng_dispute,
                rng_latent=rng_latent,
                rng_obs=rng_obs,
                rng_id=rng_id,
                reason_code=reason_codes[i],
                amount=float(amounts[i]),
                is_expired=i in expired_idx,
            )
        )

    # Frozen split, independent of generation order.
    rng_split = np.random.default_rng(SPLIT_SEED)
    permutation = rng_split.permutation(n_total)
    test_positions = set(int(i) for i in permutation[:n_test])
    for i, record in enumerate(records):
        record.split = "test" if i in test_positions else "train"

    return records


# --------------------------------------------------------------------------- #
# Serialisation                                                               #
# --------------------------------------------------------------------------- #


def _record_to_json(record: CorpusRecord) -> dict:
    """Serialise one record, keeping rupee amounts exact.

    Amounts are written as decimal *strings* rather than JSON numbers. Round
    tripping INR 2400.55 through a float and back would yield
    ``2400.550000000000181...``, and every downstream economic sum would carry
    that error.  Strings parse back to the exact :class:`Decimal`.
    """
    dispute_json = record.dispute.model_dump(mode="json")
    dispute_json["amount_inr"] = str(record.dispute.amount_inr)

    bundle_json = record.bundle.model_dump(mode="json")
    bundle_json["order"]["order_total"] = str(record.bundle.order.order_total)

    return {
        "dispute": dispute_json,
        "bundle": bundle_json,
        "won": record.won,
        "split": record.split,
        "pod_image_path": record.pod_image_path,
        # Leading underscore: stripped by load_corpus, never seen by the model.
        "_latent": record.latent,
    }


def write_corpus(records: list[CorpusRecord], data_dir: Path) -> dict[str, Path]:
    """Write the corpus to ``train.jsonl`` and ``test.jsonl``.

    Returns a mapping of split name to the file written.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    paths = {"train": data_dir / "train.jsonl", "test": data_dir / "test.jsonl"}

    handles = {name: path.open("w", encoding="utf-8") for name, path in paths.items()}
    try:
        for record in records:
            handles[record.split].write(
                json.dumps(_record_to_json(record), separators=(",", ":")) + "\n"
            )
    finally:
        for handle in handles.values():
            handle.close()

    return paths


@dataclass(slots=True)
class LoadedRecord:
    """A corpus row as the rest of the system sees it.

    Note what is absent: no latent score, no ``p_true``, no
    ``is_friendly_fraud``.  The loader strips them.  ``won`` is the only label,
    and it is a realised binary outcome, not the probability that produced it.
    """

    dispute: DisputeEvent
    bundle: EvidenceBundle
    won: int
    pod_image_path: str | None = None


def _shift_iso(value: str, delta: timedelta) -> str:
    """Translate an ISO-8601 timestamp string by ``delta``."""
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment + delta).isoformat()


def _rebase(payload: dict, delta: timedelta) -> dict:
    """Apply a rigid time translation to every timestamp in a record.

    Every model-visible feature is a *difference* of two timestamps, so a
    uniform translation leaves the feature matrix numerically identical.  Only
    ``hours_remaining`` -- read solely by ``expired_window_gate`` -- changes, and
    changing it is the entire point: it moves a corpus generated at a frozen
    anchor into the present so the gate is exercised at its designed rate rather
    than firing on every row.
    """
    dispute = payload["dispute"]
    for key in ("disputed_at", "respond_by"):
        dispute[key] = _shift_iso(dispute[key], delta)

    bundle = payload["bundle"]
    bundle["order"]["placed_at"] = _shift_iso(bundle["order"]["placed_at"], delta)
    for key in ("login_at", "account_created_at"):
        bundle["session"][key] = _shift_iso(bundle["session"][key], delta)

    delivered = bundle["pod"].get("delivered_at")
    if delivered is not None:
        bundle["pod"]["delivered_at"] = _shift_iso(delivered, delta)

    return payload


def load_corpus(path: Path, rebase_to_now: bool = True) -> list[LoadedRecord]:
    """Load a corpus split, stripping every latent field.

    Args:
        path: Path to ``train.jsonl`` or ``test.jsonl``.
        rebase_to_now: Translate all timestamps by ``now - CORPUS_EPOCH``.
            Leave True for evaluation and serving. Set False in tests that need
            byte-stable timestamps.

    Returns:
        Records carrying only what the system is allowed to see.
    """
    delta = (
        datetime.now(timezone.utc) - CORPUS_EPOCH
        if rebase_to_now
        else timedelta(0)
    )

    out: list[LoadedRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            payload.pop("_latent", None)  # the model never sees the latent
            if delta:
                payload = _rebase(payload, delta)
            out.append(
                LoadedRecord(
                    dispute=DisputeEvent.model_validate(payload["dispute"]),
                    bundle=EvidenceBundle.model_validate(payload["bundle"]),
                    won=int(payload["won"]),
                    pod_image_path=payload.get("pod_image_path"),
                )
            )
    return out


def corpus_summary(records: list[CorpusRecord]) -> dict[str, float]:
    """Return descriptive statistics for the generation banner and the report."""
    amounts = np.array([float(r.dispute.amount_inr) for r in records])
    wins = np.array([r.won for r in records], dtype=np.float64)
    p_true = np.array([r.latent.get("p_true", 0.0) for r in records])
    absent = sum(
        1
        for r in records
        if r.bundle.pod.extraction_status is ExtractionStatus.ABSENT
    )
    verified = sum(
        1
        for r in records
        if r.bundle.pod.extraction_status is ExtractionStatus.VERIFIED
    )

    return {
        "n": float(len(records)),
        "win_rate": float(wins.mean()),
        "mean_p_true": float(p_true.mean()),
        "amount_median": float(np.median(amounts)),
        "amount_mean": float(amounts.mean()),
        "amount_p95": float(np.percentile(amounts, 95)),
        "amount_max": float(amounts.max()),
        "pod_absent_rate": absent / len(records),
        "pod_verified_rate": verified / len(records),
    }


# --------------------------------------------------------------------------- #
# CLI entry point -- `make data`                                              #
# --------------------------------------------------------------------------- #


def main() -> int:
    """Generate the corpus, render the POD sample, and write both to disk.

    Invoked by ``make data`` as ``python -m data_gen.generator``.
    """
    from sentinel.config import get_settings

    settings = get_settings()
    settings.ensure_dirs()

    print("ChargeGuard :: synthetic corpus generation")
    print(f"  seeds        : MASTER={MASTER_SEED} (see data_gen/seeds.py)")
    print(f"  anchor       : {CORPUS_EPOCH.isoformat()}")
    print(
        f"  target       : {settings.n_disputes_total:,} disputes "
        f"({settings.n_disputes_train:,} train / {settings.n_disputes_test:,} test)"
    )

    records = generate_corpus(
        settings.n_disputes_total,
        settings.n_disputes_train,
        settings.n_disputes_test,
    )

    # Imported here rather than at module scope: pod_renderer imports
    # CorpusRecord from this module, so a top-level import would be circular.
    from data_gen.pod_renderer import render_corpus_sample

    images = render_corpus_sample(records, settings.pod_dir, settings.n_pod_images)
    print(f"  POD images   : {len(images)} rendered to {settings.pod_dir}")

    paths = write_corpus(records, settings.data_dir)
    for split, path in paths.items():
        count = sum(1 for r in records if r.split == split)
        print(f"  {split:<12} : {count:,} rows -> {path}")

    summary = corpus_summary(records)
    print("  corpus stats :")
    print(f"    win rate            : {summary['win_rate']:.4f}")
    print(f"    median amount       : INR {summary['amount_median']:,.2f}")
    print(f"    mean amount         : INR {summary['amount_mean']:,.2f}")
    print(f"    p95 amount          : INR {summary['amount_p95']:,.2f}")
    print(f"    max amount          : INR {summary['amount_max']:,.2f}")
    print(f"    POD absent rate     : {summary['pod_absent_rate']:.4f}")
    print(f"    POD verified rate   : {summary['pod_verified_rate']:.4f}")
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
