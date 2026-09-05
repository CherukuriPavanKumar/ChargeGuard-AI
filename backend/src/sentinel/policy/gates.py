"""Hard-override policy gates.

A gate encodes a fact about card-scheme rules or arithmetic that dominates any
probabilistic estimate.  When a gate fires, the model's opinion is discarded.

Why gates exist at all
----------------------
The expected-value rule is correct but incomplete.  It assumes ``p_i`` is a
meaningful probability of *winning a representment*, which presupposes that a
representment is procedurally possible and that the evidence would survive an
issuer's review.  Six situations break that presupposition:

* the arithmetic is unwinnable regardless of evidence (gate 1),
* the one decisive artifact for this reason code is missing (gate 2),
* fraud liability sits with the merchant and cannot be shifted (gate 3),
* the filing window has closed (gate 4),
* the cardholder's allegation is simply true (gate 5),
* or the evidence is so strong that deferring to a model would be perverse (gate 6).

Gates 1-5 force ACCEPT and exist to stop the system burning ``c`` on disputes it
cannot win.  Gate 6 forces CONTEST and exists because a calibrated model trained
on a noisy corpus will occasionally under-rate an airtight case; given the
documented FN/FP asymmetry, deferring to it there would be the expensive mistake.

Contract
--------
Every gate is a **pure function** of ``(dispute, bundle, features, settings)``
returning a :class:`~sentinel.schemas.decision.GateResult`.  Gates never raise,
never perform I/O, and never construct a :class:`~sentinel.schemas.decision.Decision`.
They are evaluated in :data:`GATE_ORDER`; the first to fire wins, and every
result -- fired or not -- is recorded on the Decision for audit.

Ordering rationale
------------------
The order is not arbitrary.  Cheapest and most absolute first:

1. ``amount_below_cost`` -- pure arithmetic, no evidence needed.
2. ``expired_window`` -- procedural bar; nothing else matters once time is up.
3. ``credit_already_processed`` -- the allegation is factually correct.
4. ``no_pod_on_non_receipt`` -- decisive artifact missing.
5. ``fraud_without_liability_shift`` -- liability cannot be shifted.
6. ``strong_evidence`` -- the sole CONTEST override, evaluated last so that no
   amount of evidence can override a procedural or arithmetic bar. An airtight
   POD on an expired dispute is still an expired dispute.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sentinel.config import Settings
from sentinel.schemas.decision import DecisionAction, GateResult
from sentinel.schemas.dispute import DisputeEvent, ReasonCode
from sentinel.schemas.evidence import EvidenceBundle, ExtractionStatus
from sentinel.schemas.features import FeatureVector

#: Signature every gate implements.
GateFn = Callable[[DisputeEvent, EvidenceBundle, FeatureVector, Settings], GateResult]


def _not_fired(name: str, rationale: str) -> GateResult:
    """Build the negative result for a gate whose precondition was not met."""
    return GateResult(
        gate_name=name, fired=False, forced_action=None, rationale=rationale
    )


# --------------------------------------------------------------------------- #
# Gate 1 -- arithmetic                                                        #
# --------------------------------------------------------------------------- #


def amount_below_cost_gate(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    features: FeatureVector,
    settings: Settings,
) -> GateResult:
    """Force ACCEPT when the disputed amount does not exceed the filing cost.

    ``A_i <= c`` means a *certain* win still loses money.  This is the degenerate
    case of the EV rule made explicit, so that the reason surfaces in the audit
    trail as arithmetic rather than as a low model score.
    """
    name = "amount_below_cost"
    cost = settings.representment_cost_inr

    if dispute.amount_inr <= cost:
        return GateResult(
            gate_name=name,
            fired=True,
            forced_action=DecisionAction.ACCEPT,
            rationale=(
                f"Disputed amount INR {dispute.amount_inr:,.2f} does not exceed the "
                f"representment cost of INR {cost:,.2f}. Even a certain win is "
                f"loss-making: EV at p=1.0 is INR {dispute.amount_inr - cost:,.2f}."
            ),
        )
    return _not_fired(
        name,
        f"Amount INR {dispute.amount_inr:,.2f} exceeds cost INR {cost:,.2f}; "
        f"a profitable recovery exists.",
    )


# --------------------------------------------------------------------------- #
# Gate 2 -- procedural bar                                                    #
# --------------------------------------------------------------------------- #


def expired_window_gate(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    features: FeatureVector,
    settings: Settings,
) -> GateResult:
    """Force ACCEPT when the scheme representment deadline has passed.

    Reads the wall clock -- deliberately.  This is a *policy* concern, not a
    feature: the feature builder stays pure and derives its time signal from
    ``respond_by - disputed_at``, while the gate asks the genuinely
    time-dependent question of whether the window is open right now.
    """
    name = "expired_window"
    hours = dispute.hours_remaining

    if hours <= 0:
        return GateResult(
            gate_name=name,
            fired=True,
            forced_action=DecisionAction.ACCEPT,
            rationale=(
                f"Representment window closed {abs(hours):,.1f} hours ago "
                f"(deadline {dispute.respond_by.isoformat()}). The scheme will "
                f"reject any filing; the cost would be spent for a certain loss."
            ),
        )
    return _not_fired(
        name, f"{hours:,.1f} hours remain before the representment deadline."
    )


# --------------------------------------------------------------------------- #
# Gate 3 -- the allegation is true                                            #
# --------------------------------------------------------------------------- #


def credit_already_processed_gate(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    features: FeatureVector,
    settings: Settings,
) -> GateResult:
    """Force ACCEPT on VISA_13.6 when a refund was in fact issued.

    Visa 13.6 alleges "credit not processed".  If our own records show a refund
    was requested and issued, the cardholder is right and contesting is both
    futile and, if repeated, grounds for scheme excessive-representment scrutiny.
    """
    name = "credit_already_processed"

    if dispute.reason_code is ReasonCode.VISA_13_6 and bundle.refund_requested:
        return GateResult(
            gate_name=name,
            fired=True,
            forced_action=DecisionAction.ACCEPT,
            rationale=(
                "Reason code VISA_13.6 (credit not processed) with a refund "
                "recorded against this order. The cardholder's allegation is "
                "supported by our own records; representment would be frivolous."
            ),
        )
    return _not_fired(
        name,
        "Not a credit-not-processed dispute with a matching refund on record.",
    )


# --------------------------------------------------------------------------- #
# Gate 4 -- decisive artifact missing                                         #
# --------------------------------------------------------------------------- #


def no_pod_on_non_receipt_gate(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    features: FeatureVector,
    settings: Settings,
) -> GateResult:
    """Force ACCEPT on a not-received dispute with no proof of delivery.

    Under Visa 13.1 proof of delivery to the cardholder's address is the only
    compelling evidence the scheme recognises.  Without it there is nothing to
    file, whatever else the bundle contains.

    Note the distinction from ``UNVERIFIED``: a document that exists but could
    not be read is still a document, and remains weakly contestable.  Only
    ``ABSENT`` -- no document at all -- fires this gate.
    """
    name = "no_pod_on_non_receipt"

    if (
        dispute.is_non_receipt_code
        and bundle.pod.extraction_status is ExtractionStatus.ABSENT
    ):
        return GateResult(
            gate_name=name,
            fired=True,
            forced_action=DecisionAction.ACCEPT,
            rationale=(
                f"Reason code {dispute.reason_code} alleges non-receipt and no "
                f"proof-of-delivery document exists (status ABSENT). Scheme rules "
                f"admit no substitute artifact; there is nothing to represent."
            ),
        )
    return _not_fired(
        name,
        "Either not a non-receipt dispute, or a proof-of-delivery document exists.",
    )


# --------------------------------------------------------------------------- #
# Gate 5 -- liability cannot be shifted                                       #
# --------------------------------------------------------------------------- #


def fraud_without_liability_shift_gate(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    features: FeatureVector,
    settings: Settings,
) -> GateResult:
    """Force ACCEPT on a fraud code with no 3-D Secure liability shift.

    Visa 10.4 and Mastercard 4837 allege the cardholder did not authorise the
    transaction.  Without ``three_ds_status == AUTHENTICATED`` the merchant
    retains fraud liability, and issuers overwhelmingly uphold these disputes
    regardless of the supporting evidence the merchant assembles.
    """
    name = "fraud_without_liability_shift"

    if dispute.is_fraud_code and not bundle.order.liability_shifted:
        return GateResult(
            gate_name=name,
            fired=True,
            forced_action=DecisionAction.ACCEPT,
            rationale=(
                f"Reason code {dispute.reason_code} is a fraud denial and 3-D "
                f"Secure status is {bundle.order.three_ds_status}, not "
                f"AUTHENTICATED. Fraud liability remains with the merchant; the "
                f"issuer has no basis to reverse."
            ),
        )
    return _not_fired(
        name,
        "Either not a fraud reason code, or 3-D Secure shifted liability to the issuer.",
    )


# --------------------------------------------------------------------------- #
# Gate 6 -- the sole CONTEST override                                         #
# --------------------------------------------------------------------------- #


def strong_evidence_gate(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    features: FeatureVector,
    settings: Settings,
) -> GateResult:
    """Force CONTEST on a verified, signed proof of delivery matching the buyer.

    All three conditions must hold: extraction ``VERIFIED``, a captured
    signature, and recipient-name similarity above
    ``settings.strong_name_match_floor``.  Together these constitute compelling
    evidence under scheme rules.

    This gate exists because of the FN/FP asymmetry.  A model trained on a noisy
    corpus will sometimes score an airtight case at 0.4; on a INR 30 000 dispute,
    deferring to that score forfeits INR 29 650 to save INR 350.  Where the
    evidence is categorically strong we do not ask the model.

    Evaluated last, so it can never override a procedural or arithmetic bar.
    """
    name = "strong_evidence"
    pod = bundle.pod
    floor = settings.strong_name_match_floor

    if (
        pod.extraction_status is ExtractionStatus.VERIFIED
        and pod.signature_captured
        and features.recipient_name_match > floor
    ):
        return GateResult(
            gate_name=name,
            fired=True,
            forced_action=DecisionAction.CONTEST,
            rationale=(
                f"Compelling evidence present: proof of delivery VERIFIED at "
                f"{pod.ocr_confidence:.0%} OCR confidence, signature captured, and "
                f"recipient name matches the cardholder at "
                f"{features.recipient_name_match:.0%} (floor {floor:.0%}). "
                f"Contesting regardless of model score."
            ),
        )
    return _not_fired(
        name,
        (
            f"Compelling-evidence bar not met "
            f"(status={pod.extraction_status}, signature={pod.signature_captured}, "
            f"name_match={features.recipient_name_match:.2f} vs floor {floor:.2f})."
        ),
    )


# --------------------------------------------------------------------------- #
# Registry                                                                    #
# --------------------------------------------------------------------------- #

#: Gates in evaluation order. First to fire wins. See "Ordering rationale" above.
GATE_ORDER: tuple[GateFn, ...] = (
    amount_below_cost_gate,
    expired_window_gate,
    credit_already_processed_gate,
    no_pod_on_non_receipt_gate,
    fraud_without_liability_shift_gate,
    strong_evidence_gate,
)

#: Stable gate names in evaluation order, for UI rendering and report tables.
GATE_NAMES: tuple[str, ...] = (
    "amount_below_cost",
    "expired_window",
    "credit_already_processed",
    "no_pod_on_non_receipt",
    "fraud_without_liability_shift",
    "strong_evidence",
)


def evaluate_all(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    features: FeatureVector,
    settings: Settings,
) -> list[GateResult]:
    """Evaluate every gate in order and return all results.

    Evaluation does **not** short-circuit: all six results are returned so the
    Decision carries the complete trace of what was considered.  The caller
    (``policy.engine``) applies first-fire-wins precedence over this list.
    """
    return [gate(dispute, bundle, features, settings) for gate in GATE_ORDER]


def first_fired(results: list[GateResult]) -> GateResult | None:
    """Return the first fired gate under evaluation order, or None."""
    for result in results:
        if result.fired:
            return result
    return None


def utc_now() -> datetime:
    """Return the current UTC time.

    Lives here rather than being called inline so the clock read is a single,
    greppable, patchable seam. The pure feature builder never touches it.
    """
    return datetime.now(timezone.utc)
