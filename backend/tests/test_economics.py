"""Property-based invariants of the arbitrage arithmetic.

These are not example tests.  Each one asserts a property that must hold across
a swept range of amounts, costs and margins, because the claims the system makes
are universal claims: *the threshold falls as the amount rises*, *the expected
value is zero exactly at break-even*, *a missed win costs more than a lost fight
above 2c*.  Checking those at three hand-picked points would prove almost
nothing.

Sweeps are deterministic grids rather than random draws.  A failing random test
that cannot be reproduced from the test name alone is a worse artifact than a
slightly coarser grid, and the properties here are smooth enough that a grid
catches any violation a sample would.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from sentinel.policy import economics

#: Amount grid spanning the corpus range, in rupees.
AMOUNTS = [
    Decimal(a)
    for a in ("150", "350", "450", "700", "1200", "2400", "5000", "12000",
              "32000", "80000")
]

#: Cost grid spanning plausible acquirer fees.
COSTS = [Decimal(c) for c in ("150", "350", "600", "1000", "1500")]

#: Risk-margin grid.
MARGINS = [1.0, 1.1, 1.2, 1.5, 2.0]


# --------------------------------------------------------------------------- #
# Threshold properties                                                        #
# --------------------------------------------------------------------------- #


class TestThresholdMonotonicity:
    @pytest.mark.parametrize("cost", COSTS)
    @pytest.mark.parametrize("margin", MARGINS)
    def test_threshold_decreases_strictly_as_amount_rises(self, cost, margin):
        """**The core property.** p* is strictly decreasing in the amount.

        This is what makes the threshold per-dispute rather than global, and it
        is the single claim the whole system rests on.
        """
        thresholds = [
            economics.decision_threshold(amount, cost, margin)
            for amount in AMOUNTS
        ]
        for earlier, later in zip(thresholds, thresholds[1:]):
            assert later < earlier, (
                f"threshold must fall as the stake rises, got {earlier} -> {later}"
            )

    @pytest.mark.parametrize("amount", AMOUNTS)
    @pytest.mark.parametrize("margin", MARGINS)
    def test_threshold_increases_with_cost(self, amount, margin):
        """A more expensive filing demands more confidence to justify it."""
        thresholds = [
            economics.decision_threshold(amount, cost, margin) for cost in COSTS
        ]
        for earlier, later in zip(thresholds, thresholds[1:]):
            assert later > earlier

    @pytest.mark.parametrize("amount", AMOUNTS)
    @pytest.mark.parametrize("cost", COSTS)
    def test_threshold_increases_with_risk_margin(self, amount, cost):
        """A larger safety margin demands more confidence."""
        thresholds = [
            economics.decision_threshold(amount, cost, margin)
            for margin in MARGINS
        ]
        for earlier, later in zip(thresholds, thresholds[1:]):
            assert later >= earlier

    @pytest.mark.parametrize("amount", AMOUNTS)
    @pytest.mark.parametrize("cost", COSTS)
    @pytest.mark.parametrize("margin", MARGINS)
    def test_threshold_matches_the_closed_form(self, amount, cost, margin):
        """The implementation is exactly ``lambda * c / A`` and nothing else."""
        expected = float(Decimal(str(margin)) * cost / amount)
        actual = economics.decision_threshold(amount, cost, margin)
        assert actual == pytest.approx(expected, rel=1e-12)

    def test_worked_examples_from_the_design_brief(self):
        """The two examples the design is specified against.

        c = 350, lambda = 1.2:
          INR 450    -> 0.933, near-certainty required
          INR 40,000 -> 0.011, worth a long shot
        """
        cost, margin = Decimal("350"), 1.2

        low = economics.decision_threshold(Decimal("450"), cost, margin)
        assert low == pytest.approx(0.9333, abs=1e-4)
        assert economics.is_threshold_reachable(low)

        high = economics.decision_threshold(Decimal("40000"), cost, margin)
        assert high == pytest.approx(0.0105, abs=1e-4)
        assert high < 0.05


class TestDegenerateThreshold:
    @pytest.mark.parametrize("cost", COSTS)
    @pytest.mark.parametrize("margin", MARGINS)
    def test_threshold_exceeds_one_below_the_breakeven_amount(self, cost, margin):
        """Below ``lambda * c`` no probability clears the bar."""
        breakeven = economics.breakeven_amount(cost, margin)
        just_below = breakeven - Decimal("1")
        if just_below <= 0:
            pytest.skip("breakeven below one rupee")

        threshold = economics.decision_threshold(just_below, cost, margin)
        assert threshold > 1.0
        assert not economics.is_threshold_reachable(threshold)

    @pytest.mark.parametrize("cost", COSTS)
    @pytest.mark.parametrize("margin", MARGINS)
    def test_threshold_is_reachable_at_and_above_breakeven(self, cost, margin):
        breakeven = economics.breakeven_amount(cost, margin)
        threshold = economics.decision_threshold(breakeven, cost, margin)

        assert threshold == pytest.approx(1.0, abs=1e-9)
        assert economics.is_threshold_reachable(threshold)

    def test_threshold_is_not_clamped(self):
        """An unreachable threshold is returned raw, not silently capped at 1.

        Clamping would make "requires certainty" indistinguishable from
        "impossible", and the audit trail would lose the difference.
        """
        threshold = economics.decision_threshold(
            Decimal("100"), Decimal("1000"), 1.2
        )
        assert threshold == pytest.approx(12.0)


class TestThresholdValidation:
    @pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1")])
    def test_rejects_non_positive_amount(self, amount):
        with pytest.raises(ValueError, match="amount_inr"):
            economics.decision_threshold(amount, Decimal("350"), 1.2)

    @pytest.mark.parametrize("cost", [Decimal("0"), Decimal("-5")])
    def test_rejects_non_positive_cost(self, cost):
        with pytest.raises(ValueError, match="cost_inr"):
            economics.decision_threshold(Decimal("1000"), cost, 1.2)

    def test_rejects_margin_below_one(self):
        """A margin under 1.0 would contest at negative expected value."""
        with pytest.raises(ValueError, match="risk_margin"):
            economics.decision_threshold(Decimal("1000"), Decimal("350"), 0.9)


# --------------------------------------------------------------------------- #
# Expected value                                                              #
# --------------------------------------------------------------------------- #


class TestExpectedValue:
    @pytest.mark.parametrize("amount", AMOUNTS)
    @pytest.mark.parametrize("cost", COSTS)
    def test_ev_is_zero_exactly_at_the_breakeven_threshold(self, amount, cost):
        """**The defining property**, at lambda = 1.0.

        At lambda = 1 the threshold *is* the break-even point, so evaluating EV
        there must give zero. At lambda > 1 the threshold deliberately sits
        above break-even and EV there equals ``(lambda - 1) * c`` -- the safety
        margin, which the next test checks explicitly.
        """
        threshold = economics.decision_threshold(amount, cost, 1.0)
        if not economics.is_threshold_reachable(threshold):
            pytest.skip("threshold unreachable at this amount/cost pair")

        ev = economics.expected_value(threshold, amount, cost)
        assert abs(ev) < Decimal("0.02"), f"EV at break-even should be 0, got {ev}"

    @pytest.mark.parametrize("amount", AMOUNTS)
    @pytest.mark.parametrize("cost", COSTS)
    @pytest.mark.parametrize("margin", [1.1, 1.2, 1.5, 2.0])
    def test_ev_at_threshold_equals_the_risk_margin_buffer(
        self, amount, cost, margin
    ):
        """With lambda > 1, EV at the threshold is exactly ``(lambda - 1) * c``."""
        threshold = economics.decision_threshold(amount, cost, margin)
        if not economics.is_threshold_reachable(threshold):
            pytest.skip("threshold unreachable at this amount/cost pair")

        ev = economics.expected_value(threshold, amount, cost)
        expected = (Decimal(str(margin)) - Decimal("1")) * cost
        assert abs(ev - expected) < Decimal("0.02")

    @pytest.mark.parametrize("amount", AMOUNTS)
    @pytest.mark.parametrize("cost", COSTS)
    def test_ev_is_strictly_increasing_in_win_probability(self, amount, cost):
        values = [
            economics.expected_value(p / 20.0, amount, cost) for p in range(21)
        ]
        for earlier, later in zip(values, values[1:]):
            assert later > earlier

    @pytest.mark.parametrize("cost", COSTS)
    def test_ev_at_zero_probability_is_exactly_minus_cost(self, cost):
        """Contesting with no chance of winning loses precisely the filing fee."""
        ev = economics.expected_value(0.0, Decimal("10000"), cost)
        assert ev == -cost

    @pytest.mark.parametrize("amount", AMOUNTS)
    @pytest.mark.parametrize("cost", COSTS)
    def test_ev_at_certainty_is_amount_minus_cost(self, amount, cost):
        ev = economics.expected_value(1.0, amount, cost)
        assert ev == amount - cost

    @pytest.mark.parametrize("p", [-0.01, 1.01, 2.0, -5.0])
    def test_rejects_probabilities_outside_the_unit_interval(self, p):
        with pytest.raises(ValueError, match="p_win"):
            economics.expected_value(p, Decimal("1000"), Decimal("350"))


# --------------------------------------------------------------------------- #
# The asymmetry -- the property that inverts standard fraud intuition         #
# --------------------------------------------------------------------------- #


class TestCostAsymmetry:
    @pytest.mark.parametrize("cost", COSTS)
    def test_fn_cost_exceeds_fp_cost_whenever_amount_exceeds_twice_cost(self, cost):
        """**The claim the whole design rests on.**

        FN = A - c and FP = c, so FN > FP exactly when A > 2c. Swept across the
        full amount grid at every cost.
        """
        for amount in AMOUNTS:
            fp = economics.false_positive_cost(cost)
            fn = economics.false_negative_cost(amount, cost)

            if amount > 2 * cost:
                assert fn > fp, (
                    f"at A={amount}, c={cost}: a missed win ({fn}) must cost "
                    f"more than a lost fight ({fp})"
                )
            elif amount < 2 * cost:
                assert fn < fp

    @pytest.mark.parametrize("cost", COSTS)
    def test_fn_and_fp_are_equal_exactly_at_twice_cost(self, cost):
        """The crossover the dashboard annotates sits precisely at A = 2c."""
        amount = 2 * cost
        assert economics.false_negative_cost(amount, cost) == (
            economics.false_positive_cost(cost)
        )

    @pytest.mark.parametrize("cost", COSTS)
    def test_fp_cost_is_flat_in_the_amount(self, cost):
        """Losing a INR 80,000 representment costs the same as a INR 400 one."""
        costs = {economics.false_positive_cost(cost) for _ in AMOUNTS}
        assert len(costs) == 1
        assert costs.pop() == cost

    @pytest.mark.parametrize("cost", COSTS)
    def test_fn_cost_is_linear_in_the_amount(self, cost):
        """FN grows one-for-one with the stake above cost."""
        for a, b in zip(AMOUNTS, AMOUNTS[1:]):
            if a <= cost:
                continue
            delta_amount = b - a
            delta_cost = economics.false_negative_cost(
                b, cost
            ) - economics.false_negative_cost(a, cost)
            assert delta_cost == delta_amount

    @pytest.mark.parametrize("cost", COSTS)
    def test_fn_cost_floors_at_zero_below_cost(self, cost):
        """Below the filing cost there was no profitable recovery to forgo."""
        assert economics.false_negative_cost(cost / 2, cost) == Decimal("0.00")
        assert economics.false_negative_cost(cost, cost) == Decimal("0.00")

    def test_asymmetry_ratio_at_the_corpus_median(self):
        """At the median dispute, a missed win costs ~5.9x a lost fight."""
        ratio = economics.cost_asymmetry_ratio(Decimal("2400"), Decimal("350"))
        assert ratio == pytest.approx(5.857, abs=0.01)

    def test_asymmetry_ratio_grows_without_bound(self):
        """At INR 80,000 the ratio is over 200x. This is why recall dominates."""
        ratio = economics.cost_asymmetry_ratio(Decimal("80000"), Decimal("350"))
        assert ratio > 200.0


# --------------------------------------------------------------------------- #
# Curve helper                                                                #
# --------------------------------------------------------------------------- #


class TestThresholdCurve:
    def test_curve_is_monotone_decreasing_and_clamped_for_plotting(self):
        curve = economics.threshold_curve(Decimal("350"), 1.2, points=40)

        assert len(curve) == 40
        amounts = [a for a, _ in curve]
        thresholds = [t for _, t in curve]

        assert amounts == sorted(amounts)
        assert all(0.0 <= t <= 1.0 for t in thresholds)
        for earlier, later in zip(thresholds, thresholds[1:]):
            assert later <= earlier

    def test_curve_spans_the_requested_range(self):
        curve = economics.threshold_curve(
            Decimal("350"), 1.2, min_amount=100.0, max_amount=100_000.0, points=25
        )
        assert curve[0][0] == pytest.approx(100.0, rel=1e-6)
        assert curve[-1][0] == pytest.approx(100_000.0, rel=1e-6)

    def test_curve_points_are_log_spaced(self):
        """Log spacing is what makes the hyperbolic decay legible when plotted."""
        curve = economics.threshold_curve(Decimal("350"), 1.2, points=10)
        ratios = [
            curve[i + 1][0] / curve[i][0] for i in range(len(curve) - 1)
        ]
        for ratio in ratios[1:]:
            assert ratio == pytest.approx(ratios[0], rel=1e-9)

    def test_rejects_degenerate_point_count(self):
        with pytest.raises(ValueError, match="points"):
            economics.threshold_curve(Decimal("350"), 1.2, points=1)


# --------------------------------------------------------------------------- #
# Cross-check against the frontend mirror                                     #
# --------------------------------------------------------------------------- #


def test_breakeven_amount_matches_the_definition():
    """``A_min = lambda * c`` -- the value the UI labels 'threshold unreachable'."""
    for cost in COSTS:
        for margin in MARGINS:
            expected = Decimal(str(margin)) * cost
            actual = economics.breakeven_amount(cost, margin)
            assert abs(actual - expected) < Decimal("0.01")


def test_threshold_and_ev_agree_about_the_decision_boundary():
    """The two formulations must never disagree about which side we are on.

    ``p >= lambda*c/A`` and ``p*A - c >= (lambda-1)*c`` are algebraically the
    same statement. Verifying that on a grid guards against one being edited
    without the other.
    """
    cost, margin = Decimal("350"), 1.2
    buffer = (Decimal(str(margin)) - Decimal("1")) * cost

    for amount in AMOUNTS:
        threshold = economics.decision_threshold(amount, cost, margin)
        if not economics.is_threshold_reachable(threshold):
            continue
        for step in range(0, 101):
            p = step / 100.0
            by_threshold = p >= threshold
            by_ev = economics.expected_value(p, amount, cost) >= buffer
            # Rounding to paisa can disagree only within one paisa of the
            # boundary; exclude that band rather than loosening the assertion.
            if math.isclose(p, threshold, abs_tol=1e-4):
                continue
            assert by_threshold == by_ev, (
                f"formulations disagree at A={amount}, p={p}"
            )
