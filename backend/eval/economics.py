r"""Economic scoring of a decision policy.

This is the scoreboard that matters.  F1 is a proxy; rupees are the objective.

Definitions
===========
For each dispute *i* let :math:`d_i \in \{0,1\}` be the policy's decision
(1 = contest), :math:`w_i \in \{0,1\}` the realised outcome had we contested,
:math:`A_i` the disputed amount and :math:`c` the representment cost.

.. code-block:: text

    Net Yield  = SUM_i  d_i * (w_i * A_i - c)
    FP cost    = SUM_i  d_i * (1 - w_i) * c
    FN cost    = SUM_i  (1 - d_i) * w_i * (A_i - c)
    Oracle     = SUM_i  max(0, w_i * A_i - c)
    eta        = Net Yield / Oracle

**Net Yield** is what the merchant actually banks: every contest costs ``c``
whether or not it lands, and returns ``A_i`` only when it does.

**Oracle** is what a policy with perfect foresight of ``w_i`` would bank.  It
contests exactly the disputes it will win, and only when the recovery exceeds
the filing cost.  It is the tightest achievable upper bound, and it is *not*
``SUM w_i * A_i`` -- even the oracle pays ``c`` on every dispute it contests,
and declines the ones where ``A_i < c``.

**eta** (oracle efficiency) is therefore in [0, 1] for any sane policy and is
the single number to compare policies on.  It normalises away the corpus size
and the amount distribution, so it answers "what fraction of the theoretically
available money did this policy capture?" rather than "how big was the test set?"

Why eta and not accuracy
========================
A policy that contests everything achieves perfect recall and near-zero eta,
because it burns ``c`` on thousands of unwinnable disputes.  A policy that
contests nothing achieves zero of both.  Only a metric denominated in money
distinguishes a policy that is right about the *expensive* disputes from one
that is right about the *numerous* ones -- and given that ``A_i`` spans two
orders of magnitude, those are very different policies.

A note on the FN counterfactual
===============================
``FN cost`` uses ``A_i - c``, not ``A_i``: had we contested and won, we would
still have paid the filing cost.  Charging the full amount to a false negative
would overstate the loss by ``c`` per row and flatter any high-recall policy.
This is only computable at all because the corpus is synthetic and ``w_i`` is
known for disputes we declined -- in production the counterfactual is
unobservable, which is precisely why the offline harness earns its keep.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

_PAISA = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class EconomicResult:
    """Economic outcome of one policy over one evaluation set."""

    name: str
    """Policy label, as it appears in the report and the dashboard."""

    net_yield_inr: Decimal
    """Rupees banked: ``SUM d_i (w_i A_i - c)``."""

    oracle_yield_inr: Decimal
    """Rupees a perfect-foresight policy would bank."""

    oracle_efficiency: float
    """``net_yield / oracle_yield``. The headline comparison number."""

    fp_cost_inr: Decimal
    """Wasted filing costs on contests that lost."""

    fn_cost_inr: Decimal
    """Recovery forgone on winnable disputes we conceded."""

    fp_fn_ratio: float
    """``fn_cost / fp_cost``. Quantifies the asymmetry on this corpus."""

    n_contested: int
    """Count of disputes contested."""

    n_total: int
    """Evaluation set size."""

    contest_rate: float
    """``n_contested / n_total``."""

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view for ``metrics.json``."""
        return {
            "name": self.name,
            "net_yield_inr": float(self.net_yield_inr),
            "oracle_yield_inr": float(self.oracle_yield_inr),
            "oracle_efficiency": round(self.oracle_efficiency, 6),
            "fp_cost_inr": float(self.fp_cost_inr),
            "fn_cost_inr": float(self.fn_cost_inr),
            "fp_fn_ratio": round(self.fp_fn_ratio, 6),
            "n_contested": self.n_contested,
            "n_total": self.n_total,
            "contest_rate": round(self.contest_rate, 6),
        }


def _quantise(value: Decimal) -> Decimal:
    """Round a rupee amount to paisa."""
    return value.quantize(_PAISA, rounding=ROUND_HALF_UP)


def oracle_yield(amounts: list[Decimal], outcomes: np.ndarray, cost: Decimal) -> Decimal:
    r"""Return ``SUM_i max(0, w_i A_i - c)``.

    The perfect-foresight benchmark.  Note it declines disputes where
    :math:`A_i < c` even when :math:`w_i = 1`: winning a INR 200 dispute for a
    INR 350 filing fee is a loss, and an oracle does not take it.
    """
    total = Decimal("0")
    for amount, won in zip(amounts, outcomes):
        if int(won) == 1:
            gain = amount - cost
            if gain > 0:
                total += gain
    return _quantise(total)


def score_policy(
    name: str,
    decisions: np.ndarray,
    amounts: list[Decimal],
    outcomes: np.ndarray,
    cost: Decimal,
) -> EconomicResult:
    """Score one decision policy in rupees.

    Args:
        name: Policy label for the report.
        decisions: ``d_i`` per dispute, 1 = contest.
        amounts: ``A_i`` per dispute as exact Decimals.
        outcomes: ``w_i`` per dispute, the realised counterfactual outcome.
        cost: The representment cost ``c``.

    Returns:
        A fully populated :class:`EconomicResult`.

    Raises:
        ValueError: on length mismatch between the three arrays.
    """
    d = np.asarray(decisions, dtype=np.int64)
    w = np.asarray(outcomes, dtype=np.int64)

    if not (len(d) == len(w) == len(amounts)):
        raise ValueError(
            f"length mismatch: decisions={len(d)}, outcomes={len(w)}, "
            f"amounts={len(amounts)}"
        )

    net = Decimal("0")
    fp_cost = Decimal("0")
    fn_cost = Decimal("0")

    for decision, won, amount in zip(d, w, amounts):
        if int(decision) == 1:
            if int(won) == 1:
                net += amount - cost
            else:
                net -= cost
                fp_cost += cost
        else:
            if int(won) == 1:
                forgone = amount - cost
                if forgone > 0:
                    fn_cost += forgone

    oracle = oracle_yield(amounts, w, cost)
    efficiency = float(net / oracle) if oracle > 0 else 0.0
    ratio = float(fn_cost / fp_cost) if fp_cost > 0 else 0.0
    n_contested = int(np.sum(d == 1))
    n_total = len(d)

    return EconomicResult(
        name=name,
        net_yield_inr=_quantise(net),
        oracle_yield_inr=oracle,
        oracle_efficiency=efficiency,
        fp_cost_inr=_quantise(fp_cost),
        fn_cost_inr=_quantise(fn_cost),
        fp_fn_ratio=ratio,
        n_contested=n_contested,
        n_total=n_total,
        contest_rate=n_contested / n_total if n_total else 0.0,
    )


def realised_asymmetry(
    amounts: list[Decimal], cost: Decimal
) -> dict[str, float]:
    """Summarise the FN/FP cost asymmetry actually present in this corpus.

    Reports the share of disputes above ``2c`` -- the point at which a missed
    win costs more than a lost fight -- and the mean and median ratios among
    those.  Puts a number on the claim that drives the whole design.
    """
    values = np.asarray([float(a) for a in amounts], dtype=np.float64)
    c = float(cost)

    above = values > 2.0 * c
    ratios = np.where(values > c, (values - c) / c, 0.0)

    return {
        "cost_inr": c,
        "share_above_2c": round(float(above.mean()), 6),
        "mean_fn_fp_ratio": round(float(ratios.mean()), 4),
        "median_fn_fp_ratio": round(float(np.median(ratios)), 4),
        "max_fn_fp_ratio": round(float(ratios.max()), 4),
    }
