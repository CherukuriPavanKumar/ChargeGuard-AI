"""Every gate, both branches, plus ordering precedence.

Structure: one class per gate, each with a ``test_fires`` and a
``test_does_not_fire``, followed by a precedence class that constructs disputes
where *two* gates could fire and asserts the earlier one wins.

The precedence tests are the ones that matter most.  A gate that works in
isolation and loses a race it should have won is a silent policy bug: the
decision is still recorded, still auditable, and still wrong.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from sentinel.features import builder
from sentinel.policy import engine, gates
from sentinel.schemas.decision import DecisionAction
from sentinel.schemas.dispute import ReasonCode
from sentinel.schemas.evidence import ExtractionStatus, ThreeDSStatus


def _evaluate(gate_fn, dispute, bundle, settings):
    """Run a single gate against freshly built features."""
    features = builder.build(dispute, bundle)
    return gate_fn(dispute, bundle, features, settings)


# --------------------------------------------------------------------------- #
# Gate 1 -- amount_below_cost                                                 #
# --------------------------------------------------------------------------- #


class TestAmountBelowCostGate:
    def test_fires_when_amount_at_or_below_cost(
        self, make_dispute, base_bundle, settings
    ):
        """A <= c: even a certain win loses money, so ACCEPT is forced."""
        dispute = make_dispute(amount="300.00")
        result = _evaluate(
            gates.amount_below_cost_gate, dispute, base_bundle, settings
        )

        assert result.fired is True
        assert result.forced_action is DecisionAction.ACCEPT
        assert "300" in result.rationale

    def test_fires_exactly_at_cost_boundary(
        self, make_dispute, base_bundle, settings
    ):
        """The boundary is inclusive: A == c is still not worth contesting."""
        dispute = make_dispute(amount=settings.representment_cost_inr)
        result = _evaluate(
            gates.amount_below_cost_gate, dispute, base_bundle, settings
        )
        assert result.fired is True

    def test_does_not_fire_above_cost(self, make_dispute, base_bundle, settings):
        """One paisa above cost leaves a profitable recovery available."""
        dispute = make_dispute(
            amount=settings.representment_cost_inr + Decimal("0.01")
        )
        result = _evaluate(
            gates.amount_below_cost_gate, dispute, base_bundle, settings
        )

        assert result.fired is False
        assert result.forced_action is None


# --------------------------------------------------------------------------- #
# Gate 2 -- expired_window                                                    #
# --------------------------------------------------------------------------- #


class TestExpiredWindowGate:
    def test_fires_when_deadline_passed(
        self, make_dispute, base_bundle, settings
    ):
        """A closed window makes the dispute unfileable at any probability."""
        dispute = make_dispute(hours_remaining=-5000.0)
        result = _evaluate(
            gates.expired_window_gate, dispute, base_bundle, settings
        )

        assert result.fired is True
        assert result.forced_action is DecisionAction.ACCEPT

    def test_does_not_fire_while_window_open(
        self, make_dispute, base_bundle, settings
    ):
        dispute = make_dispute(hours_remaining=100_000.0)
        result = _evaluate(
            gates.expired_window_gate, dispute, base_bundle, settings
        )

        assert result.fired is False
        assert "hours remain" in result.rationale


# --------------------------------------------------------------------------- #
# Gate 3 -- credit_already_processed                                          #
# --------------------------------------------------------------------------- #


class TestCreditAlreadyProcessedGate:
    def test_fires_on_credit_code_with_refund(
        self, make_dispute, make_bundle, settings
    ):
        """VISA 13.6 plus a refund on record means the cardholder is right."""
        dispute = make_dispute(reason_code=ReasonCode.VISA_13_6)
        bundle = make_bundle(refund_requested=True)
        result = _evaluate(
            gates.credit_already_processed_gate, dispute, bundle, settings
        )

        assert result.fired is True
        assert result.forced_action is DecisionAction.ACCEPT

    def test_does_not_fire_on_credit_code_without_refund(
        self, make_dispute, make_bundle, settings
    ):
        """No refund on record means the allegation is contestable."""
        dispute = make_dispute(reason_code=ReasonCode.VISA_13_6)
        bundle = make_bundle(refund_requested=False)
        result = _evaluate(
            gates.credit_already_processed_gate, dispute, bundle, settings
        )
        assert result.fired is False

    def test_does_not_fire_on_other_code_with_refund(
        self, make_dispute, make_bundle, settings
    ):
        """A refund on a non-credit code is not this gate's business."""
        dispute = make_dispute(reason_code=ReasonCode.VISA_13_1)
        bundle = make_bundle(refund_requested=True)
        result = _evaluate(
            gates.credit_already_processed_gate, dispute, bundle, settings
        )
        assert result.fired is False


# --------------------------------------------------------------------------- #
# Gate 4 -- no_pod_on_non_receipt                                             #
# --------------------------------------------------------------------------- #


class TestNoPodOnNonReceiptGate:
    @pytest.mark.parametrize(
        "reason", [ReasonCode.VISA_13_1, ReasonCode.MC_4853]
    )
    def test_fires_on_non_receipt_with_absent_pod(
        self, reason, make_dispute, make_bundle, make_pod, settings
    ):
        """Both non-receipt codes require a POD; ABSENT leaves nothing to file."""
        dispute = make_dispute(reason_code=reason)
        bundle = make_bundle(pod=make_pod(status=ExtractionStatus.ABSENT))
        result = _evaluate(
            gates.no_pod_on_non_receipt_gate, dispute, bundle, settings
        )

        assert result.fired is True
        assert result.forced_action is DecisionAction.ACCEPT

    def test_does_not_fire_when_pod_unreadable_but_present(
        self, make_dispute, make_bundle, make_pod, settings
    ):
        """UNVERIFIED is not ABSENT.

        A document we could not read is still a document. Conflating the two
        would concede disputes that remain weakly contestable on other evidence,
        which is the expensive direction to be wrong in.
        """
        dispute = make_dispute(reason_code=ReasonCode.VISA_13_1)
        bundle = make_bundle(pod=make_pod(status=ExtractionStatus.UNVERIFIED))
        result = _evaluate(
            gates.no_pod_on_non_receipt_gate, dispute, bundle, settings
        )
        assert result.fired is False

    def test_does_not_fire_on_fraud_code_without_pod(
        self, make_dispute, make_bundle, make_pod, settings
    ):
        """A fraud denial does not turn on proof of delivery."""
        dispute = make_dispute(reason_code=ReasonCode.VISA_10_4)
        bundle = make_bundle(pod=make_pod(status=ExtractionStatus.ABSENT))
        result = _evaluate(
            gates.no_pod_on_non_receipt_gate, dispute, bundle, settings
        )
        assert result.fired is False


# --------------------------------------------------------------------------- #
# Gate 5 -- fraud_without_liability_shift                                     #
# --------------------------------------------------------------------------- #


class TestFraudWithoutLiabilityShiftGate:
    @pytest.mark.parametrize(
        "reason", [ReasonCode.VISA_10_4, ReasonCode.MC_4837]
    )
    @pytest.mark.parametrize(
        "three_ds",
        [ThreeDSStatus.ATTEMPTED, ThreeDSStatus.NOT_ENROLLED, ThreeDSStatus.FAILED],
    )
    def test_fires_on_fraud_without_authentication(
        self, reason, three_ds, make_dispute, make_bundle, settings
    ):
        """Every non-AUTHENTICATED status leaves liability with the merchant."""
        dispute = make_dispute(reason_code=reason)
        bundle = make_bundle(three_ds=three_ds)
        result = _evaluate(
            gates.fraud_without_liability_shift_gate, dispute, bundle, settings
        )

        assert result.fired is True
        assert result.forced_action is DecisionAction.ACCEPT

    def test_does_not_fire_with_liability_shift(
        self, make_dispute, make_bundle, settings
    ):
        """AUTHENTICATED shifts liability to the issuer; the dispute is winnable."""
        dispute = make_dispute(reason_code=ReasonCode.VISA_10_4)
        bundle = make_bundle(three_ds=ThreeDSStatus.AUTHENTICATED)
        result = _evaluate(
            gates.fraud_without_liability_shift_gate, dispute, bundle, settings
        )
        assert result.fired is False

    def test_does_not_fire_on_non_fraud_code(
        self, make_dispute, make_bundle, settings
    ):
        """A not-received claim is unaffected by the liability shift."""
        dispute = make_dispute(reason_code=ReasonCode.VISA_13_1)
        bundle = make_bundle(three_ds=ThreeDSStatus.FAILED)
        result = _evaluate(
            gates.fraud_without_liability_shift_gate, dispute, bundle, settings
        )
        assert result.fired is False


# --------------------------------------------------------------------------- #
# Gate 6 -- strong_evidence (the only CONTEST override)                       #
# --------------------------------------------------------------------------- #


class TestStrongEvidenceGate:
    def test_fires_on_verified_signed_matching_pod(
        self, base_dispute, base_bundle, settings
    ):
        """All three conditions met: VERIFIED, signed, name match above floor."""
        result = _evaluate(
            gates.strong_evidence_gate, base_dispute, base_bundle, settings
        )

        assert result.fired is True
        assert result.forced_action is DecisionAction.CONTEST

    def test_does_not_fire_without_signature(
        self, base_dispute, make_bundle, make_pod, settings
    ):
        result = _evaluate(
            gates.strong_evidence_gate,
            base_dispute,
            make_bundle(pod=make_pod(signature=False)),
            settings,
        )
        assert result.fired is False

    def test_does_not_fire_on_low_confidence_extraction(
        self, base_dispute, make_bundle, make_pod, settings
    ):
        """A signed, name-matching POD we could not read cleanly is not compelling."""
        result = _evaluate(
            gates.strong_evidence_gate,
            base_dispute,
            make_bundle(pod=make_pod(status=ExtractionStatus.LOW_CONFIDENCE)),
            settings,
        )
        assert result.fired is False

    def test_does_not_fire_when_recipient_name_differs(
        self, base_dispute, make_bundle, make_pod, settings
    ):
        """A parcel signed for by someone else is not compelling evidence."""
        result = _evaluate(
            gates.strong_evidence_gate,
            base_dispute,
            make_bundle(pod=make_pod(recipient="Vikram Chaudhary")),
            settings,
        )
        assert result.fired is False


# --------------------------------------------------------------------------- #
# Ordering precedence                                                         #
# --------------------------------------------------------------------------- #


class TestGateOrdering:
    def test_registry_order_matches_published_names(self):
        """GATE_ORDER and GATE_NAMES must not drift apart.

        GATE_NAMES is what the report and the UI render; GATE_ORDER is what
        actually executes. A mismatch would show an audit trail that does not
        describe the policy that ran.
        """
        executed = [
            fn.__name__.removesuffix("_gate") for fn in gates.GATE_ORDER
        ]
        assert tuple(executed) == gates.GATE_NAMES

    def test_arithmetic_beats_strong_evidence(
        self, make_dispute, base_bundle, settings
    ):
        """A INR 200 dispute with perfect evidence is still not worth INR 350.

        ``amount_below_cost`` is evaluated first precisely so that no quantity of
        evidence can override arithmetic.
        """
        dispute = make_dispute(amount="200.00")
        features = builder.build(dispute, base_bundle)

        results = gates.evaluate_all(dispute, base_bundle, features, settings)
        fired = gates.first_fired(results)

        assert fired is not None
        assert fired.gate_name == "amount_below_cost"
        assert fired.forced_action is DecisionAction.ACCEPT

        # The strong-evidence gate genuinely also fires; it simply loses.
        by_name = {r.gate_name: r for r in results}
        assert by_name["strong_evidence"].fired is True

    def test_expiry_beats_strong_evidence(
        self, make_dispute, base_bundle, settings
    ):
        """An airtight POD on an expired dispute is still an expired dispute."""
        dispute = make_dispute(amount="40000.00", hours_remaining=-10.0)
        features = builder.build(dispute, base_bundle)

        results = gates.evaluate_all(dispute, base_bundle, features, settings)
        fired = gates.first_fired(results)

        assert fired is not None
        assert fired.gate_name == "expired_window"

        by_name = {r.gate_name: r for r in results}
        assert by_name["strong_evidence"].fired is True

    def test_liability_gate_beats_strong_evidence(
        self, make_dispute, make_bundle, settings
    ):
        """Compelling delivery proof does not rescue an unauthenticated 10.4.

        Delivering the goods does not answer "I did not authorise this".
        """
        dispute = make_dispute(
            amount="25000.00", reason_code=ReasonCode.VISA_10_4
        )
        bundle = make_bundle(three_ds=ThreeDSStatus.NOT_ENROLLED)
        features = builder.build(dispute, bundle)

        results = gates.evaluate_all(dispute, bundle, features, settings)
        fired = gates.first_fired(results)

        assert fired is not None
        assert fired.gate_name == "fraud_without_liability_shift"

        by_name = {r.gate_name: r for r in results}
        assert by_name["strong_evidence"].fired is True

    def test_every_gate_is_recorded_whether_or_not_it_fires(
        self, base_dispute, base_bundle, settings
    ):
        """The trace is complete: all six results, in order, always."""
        features = builder.build(base_dispute, base_bundle)
        results = gates.evaluate_all(base_dispute, base_bundle, features, settings)

        assert len(results) == len(gates.GATE_ORDER)
        assert tuple(r.gate_name for r in results) == gates.GATE_NAMES
        assert all(r.rationale for r in results), "every gate must justify itself"

    def test_non_firing_gates_carry_no_forced_action(
        self, base_dispute, base_bundle, settings
    ):
        features = builder.build(base_dispute, base_bundle)
        results = gates.evaluate_all(base_dispute, base_bundle, features, settings)

        for result in results:
            if not result.fired:
                assert result.forced_action is None

    def test_gates_are_pure_and_repeatable(
        self, base_dispute, base_bundle, settings
    ):
        """Gates must not accumulate state between evaluations."""
        features = builder.build(base_dispute, base_bundle)
        first = gates.evaluate_all(base_dispute, base_bundle, features, settings)
        second = gates.evaluate_all(base_dispute, base_bundle, features, settings)

        assert [(r.gate_name, r.fired) for r in first] == [
            (r.gate_name, r.fired) for r in second
        ]


# --------------------------------------------------------------------------- #
# Engine integration                                                          #
# --------------------------------------------------------------------------- #


class TestEngineHonoursGates:
    def test_fired_gate_overrides_a_high_model_score(
        self, make_dispute, make_bundle, settings
    ):
        """p_win = 0.99 does not survive a hard ACCEPT gate."""
        dispute = make_dispute(
            amount="30000.00", reason_code=ReasonCode.VISA_10_4
        )
        bundle = make_bundle(three_ds=ThreeDSStatus.FAILED)
        features = builder.build(dispute, bundle)

        decision = engine.decide(
            dispute=dispute,
            bundle=bundle,
            features=features,
            p_win=0.99,
            model_version="test",
            settings=settings,
        )

        assert decision.action is DecisionAction.ACCEPT
        assert decision.deciding_reason == "fraud_without_liability_shift"

    def test_fired_gate_overrides_a_low_model_score(
        self, base_dispute, base_bundle, settings
    ):
        """p_win = 0.01 does not survive the strong-evidence CONTEST gate."""
        features = builder.build(base_dispute, base_bundle)

        decision = engine.decide(
            dispute=base_dispute,
            bundle=base_bundle,
            features=features,
            p_win=0.01,
            model_version="test",
            settings=settings,
        )

        assert decision.action is DecisionAction.CONTEST
        assert decision.deciding_reason == "strong_evidence"

    def test_ev_rule_decides_when_no_gate_fires(
        self, make_dispute, make_bundle, make_pod, settings
    ):
        """With every gate quiet, the arithmetic decides and says so."""
        dispute = make_dispute(
            amount="10000.00", reason_code=ReasonCode.VISA_13_3
        )
        bundle = make_bundle(pod=make_pod(signature=False))
        features = builder.build(dispute, bundle)

        decision = engine.decide(
            dispute=dispute,
            bundle=bundle,
            features=features,
            p_win=0.50,
            model_version="test",
            settings=settings,
        )

        assert decision.deciding_reason == engine.EV_RULE
        assert decision.fired_gate is None
        assert decision.action is DecisionAction.CONTEST
        assert decision.win_probability >= decision.threshold

    def test_engine_rejects_a_probability_outside_the_unit_interval(
        self, base_dispute, base_bundle, base_features, settings
    ):
        """A broken model must fail loudly rather than be silently clamped."""
        with pytest.raises(ValueError, match="probability"):
            engine.decide(
                dispute=base_dispute,
                bundle=base_bundle,
                features=base_features,
                p_win=1.4,
                model_version="test",
                settings=settings,
            )

    def test_expected_value_is_recorded_even_on_gated_decisions(
        self, make_dispute, make_bundle, settings
    ):
        """A gated decision still answers 'what would this have been worth?'."""
        dispute = make_dispute(
            amount="30000.00", reason_code=ReasonCode.VISA_10_4
        )
        bundle = make_bundle(three_ds=ThreeDSStatus.FAILED)
        features = builder.build(dispute, bundle)

        decision = engine.decide(
            dispute=dispute,
            bundle=bundle,
            features=features,
            p_win=0.80,
            model_version="test",
            settings=settings,
        )

        assert decision.action is DecisionAction.ACCEPT
        # 0.8 * 30000 - 350 = 23650: the value the gate deliberately forgoes.
        assert decision.expected_value_inr == Decimal("23650.00")
