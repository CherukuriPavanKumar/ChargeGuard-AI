r"""The arbitrage arithmetic. This is the idea the whole codebase exists to express.

MIRROR: ``frontend/src/lib/economics.js`` implements these identical formulas
for the client-side simulator fallback. Any change here must be mirrored there.

Derivation
==========

For dispute *i* with amount :math:`A_i`, we choose an action
:math:`d_i \in \{0, 1\}` (0 = accept, 1 = contest).  Let :math:`p_i` be the
calibrated probability that a representment succeeds, and :math:`c` the
fully-loaded cost of filing one.

If we **accept**, the chargeback stands.  The amount is already debited, so the
incremental cash flow is zero::

    E[accept] = 0

If we **contest**, we pay :math:`c` unconditionally and recover :math:`A_i`
with probability :math:`p_i`::

    E[contest] = p_i * A_i - c

The difference is the expected value of fighting::

    EV_i = E[contest] - E[accept] = p_i * A_i - c

Contesting is worthwhile when :math:`EV_i \ge 0`, i.e. :math:`p_i \ge c / A_i`.
We add a risk margin :math:`\lambda \ge 1` to absorb calibration error, giving
the operative rule::

    contest  <=>  p_i >= lambda * c / A_i  =:  p*_i

**The threshold is per-dispute, not global.**  This is the entire point.  A
single global cutoff -- "contest anything above 60% confidence" -- is
economically illiterate, because it ignores the amount at stake.  With
:math:`c = 350` and :math:`\lambda = 1.2`:

===========  ==========  ============================================
:math:`A_i`  :math:`p*`  reading
===========  ==========  ============================================
   INR   450       0.933  near-certainty required
   INR 2 400       0.175  the median dispute
   INR 40 000      0.011  worth contesting on a long shot
===========  ==========  ============================================

The asymmetry
=============

The two ways to be wrong do not cost the same amount.

*False positive* -- we contested and lost.  We are out the filing cost only::

    FP_i = c

*False negative* -- we accepted a dispute we would have won.  We forfeited the
recovery and saved the filing cost::

    FN_i = A_i - c

So :math:`FN_i > FP_i` whenever :math:`A_i > 2c`, which for :math:`c = 350`
means every dispute above INR 700 -- the overwhelming majority of the corpus.
At the median dispute of INR 2 400 the ratio is already ~5.9x; at INR 40 000 it
is ~113x.

This **inverts the standard fraud-detection intuition**.  In transaction fraud
you tune for precision, because a false positive blocks a paying customer.
Here a false positive costs INR 350 and a false negative can cost INR 40 000.
The correct posture is aggressive recall, bounded only by the per-dispute
threshold above.  That inversion is visible in the gates (only six hard
ACCEPT overrides, all rule-based rather than confidence-based), in the
evaluation harness (which reports net yield in rupees, not F1), and in the
dashboard (which plots FP and FN cost curves against each other).

Degenerate case
===============

When :math:`\lambda c / A_i > 1` the threshold is unreachable: no probability,
not even certainty, makes the arithmetic work.  This happens whenever
:math:`A_i < \lambda c`.  We return the true (>1) threshold rather than
clamping, so callers can distinguish "unreachable" from "requires certainty",
and :func:`is_threshold_reachable` makes the check explicit at every call site.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

#: Rupee quantum used for all monetary rounding.
_PAISA = Decimal("0.01")


def decision_threshold(
    amount_inr: Decimal, cost_inr: Decimal, risk_margin: float
) -> float:
    r"""Return the per-dispute break-even win probability :math:`p*_i`.

    ``p* = lambda * c / A_i``

    Args:
        amount_inr: Disputed amount :math:`A_i`. Must be positive.
        cost_inr: Representment cost :math:`c`. Must be positive.
        risk_margin: Risk margin :math:`\lambda`, at least 1.0.

    Returns:
        The threshold as a float.  **May exceed 1.0**, which signals that the
        dispute is unwinnable on economics alone regardless of confidence.  The
        value is deliberately not clamped -- see :func:`is_threshold_reachable`.

    Raises:
        ValueError: if the amount or cost is non-positive, or the margin < 1.
    """
    if amount_inr <= 0:
        raise ValueError(f"amount_inr must be positive, got {amount_inr}")
    if cost_inr <= 0:
        raise ValueError(f"cost_inr must be positive, got {cost_inr}")
    if risk_margin < 1.0:
        raise ValueError(f"risk_margin must be >= 1.0, got {risk_margin}")

    return float(Decimal(str(risk_margin)) * cost_inr / amount_inr)


def is_threshold_reachable(threshold: float) -> bool:
    """True when some probability in [0, 1] could clear the threshold.

    A threshold above 1.0 is unreachable: even a certain win does not repay the
    risk-adjusted filing cost.  Callers must force ACCEPT in that case rather
    than comparing against a clamped value, which would spuriously contest
    high-confidence, low-value disputes.
    """
    return threshold <= 1.0


def expected_value(p_win: float, amount_inr: Decimal, cost_inr: Decimal) -> Decimal:
    r"""Return :math:`EV_i = p_i A_i - c` in rupees.

    This is the *difference* between contesting and accepting, not the absolute
    value of contesting -- accepting has zero incremental cash flow, so the two
    coincide.  Negative values quantify the loss avoided by conceding.

    Args:
        p_win: Calibrated win probability in [0, 1].
        amount_inr: Disputed amount.
        cost_inr: Representment cost.

    Returns:
        Expected value in rupees, quantised to paisa.

    Raises:
        ValueError: if ``p_win`` is outside [0, 1].
    """
    if not 0.0 <= p_win <= 1.0:
        raise ValueError(f"p_win must be in [0, 1], got {p_win}")

    ev = Decimal(str(p_win)) * amount_inr - cost_inr
    return ev.quantize(_PAISA, rounding=ROUND_HALF_UP)


def false_positive_cost(cost_inr: Decimal) -> Decimal:
    r"""Cost of contesting a dispute we go on to lose.

    ``FP = c``

    We spend the filing cost and recover nothing.  Note that this is *flat* in
    the disputed amount: losing a INR 40 000 representment costs exactly as much
    as losing a INR 900 one, because the amount was already debited either way.
    """
    return cost_inr.quantize(_PAISA, rounding=ROUND_HALF_UP)


def false_negative_cost(amount_inr: Decimal, cost_inr: Decimal) -> Decimal:
    r"""Opportunity cost of accepting a dispute we would have won.

    ``FN = A_i - c``

    We forfeit the recovery but save the filing cost.  Unlike the false-positive
    cost this grows *linearly* in the disputed amount, which is the source of
    the asymmetry documented in the module docstring.

    Returns zero rather than a negative number when ``A_i <= c``: there was no
    profitable recovery to forgo, so nothing was lost.
    """
    forgone = amount_inr - cost_inr
    if forgone < 0:
        forgone = Decimal("0")
    return forgone.quantize(_PAISA, rounding=ROUND_HALF_UP)


def cost_asymmetry_ratio(amount_inr: Decimal, cost_inr: Decimal) -> float:
    """Return ``FN / FP`` -- how many times worse a missed win is than a lost fight.

    Returns ``0.0`` when the false-negative cost is zero (amount at or below
    cost), where the ratio is not meaningful.
    """
    fp = false_positive_cost(cost_inr)
    fn = false_negative_cost(amount_inr, cost_inr)
    if fn == 0:
        return 0.0
    return float(fn / fp)


def breakeven_amount(cost_inr: Decimal, risk_margin: float) -> Decimal:
    r"""Smallest amount for which the threshold is reachable at all.

    ``A_min = lambda * c``.  Below this, :func:`decision_threshold` exceeds 1.0
    and ACCEPT is forced by arithmetic rather than by evidence.
    """
    return (Decimal(str(risk_margin)) * cost_inr).quantize(
        _PAISA, rounding=ROUND_HALF_UP
    )


def threshold_curve(
    cost_inr: Decimal,
    risk_margin: float,
    min_amount: float = 100.0,
    max_amount: float = 100_000.0,
    points: int = 60,
) -> list[tuple[float, float]]:
    """Sample ``(amount, threshold)`` pairs on a log amount axis.

    Used by the evaluation report and mirrored by the frontend's arbitrage
    visualiser to draw the hyperbolic decay of ``p*`` as the stake rises.
    Thresholds are clamped to 1.0 for plotting only; the underlying rule is
    unclamped.
    """
    if points < 2:
        raise ValueError(f"points must be >= 2, got {points}")

    log_min, log_max = math.log(min_amount), math.log(max_amount)
    step = (log_max - log_min) / (points - 1)

    curve: list[tuple[float, float]] = []
    for i in range(points):
        amount = math.exp(log_min + i * step)
        raw = decision_threshold(Decimal(str(round(amount, 2))), cost_inr, risk_margin)
        curve.append((amount, min(raw, 1.0)))
    return curve
