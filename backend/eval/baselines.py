"""Comparator policies.

A metric without a baseline is a decoration.  Four comparators are implemented,
chosen because each one is a policy a real merchant actually runs:

``contest_nothing``
    The default state of most small merchants: absorb every chargeback. Banks
    zero, and is the reason the problem is worth solving. Its FN cost is the
    total recoverable value on the table.

``contest_everything``
    The naive automation: fight every dispute. Achieves perfect recall and
    demonstrates why recall alone is not the objective -- it pays ``c`` on
    thousands of unwinnable disputes and can go *negative*.

``fixed_threshold``
    The policy a competent analyst writes without a model: contest anything
    above a round-number rupee cutoff. This is the strongest non-ML baseline and
    the honest one to beat, because it already captures the single most
    important insight -- that amount matters.

``evidence_heuristic``
    The policy a competent analyst writes *with* domain knowledge but no model:
    contest when a proof of delivery exists and carries a signature. Encodes the
    correct qualitative rule for the largest reason-code cluster.

Every baseline returns a decision array of the same shape as ChargeGuard's, and all
five are scored by the same :func:`eval.economics.score_policy`.  None of them
constructs a :class:`~sentinel.schemas.decision.Decision`: they are policies over
arrays, not participants in the decision pipeline, and INVARIANT 1 holds.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from data_gen.generator import LoadedRecord
from sentinel.schemas.evidence import ExtractionStatus

#: Rupee cutoff for the fixed-threshold baseline. A round number an analyst
#: would actually pick, deliberately not tuned against the test set -- tuning it
#: would make it a fitted model masquerading as a baseline.
FIXED_THRESHOLD_INR: Decimal = Decimal("5000")


@dataclass(frozen=True, slots=True)
class Baseline:
    """A named comparator policy over the evaluation set."""

    name: str
    """Label as it appears in the report and the dashboard chart."""

    describe: str
    """One-line explanation of what this policy does and who runs it."""

    decide: Callable[[list[LoadedRecord]], np.ndarray]
    """Maps the evaluation set to a 0/1 decision array."""


def contest_nothing(records: list[LoadedRecord]) -> np.ndarray:
    """Accept every dispute. The status quo for most merchants."""
    return np.zeros(len(records), dtype=np.int64)


def contest_everything(records: list[LoadedRecord]) -> np.ndarray:
    """Contest every dispute. Perfect recall, and frequently negative yield."""
    return np.ones(len(records), dtype=np.int64)


def fixed_threshold(records: list[LoadedRecord]) -> np.ndarray:
    """Contest every dispute at or above :data:`FIXED_THRESHOLD_INR`.

    The strongest non-ML baseline: it already knows that amount is the dominant
    economic variable.  What it cannot do is vary its confidence requirement
    with the stake, which is the specific thing the EV rule adds.
    """
    return np.asarray(
        [1 if r.dispute.amount_inr >= FIXED_THRESHOLD_INR else 0 for r in records],
        dtype=np.int64,
    )


def evidence_heuristic(records: list[LoadedRecord]) -> np.ndarray:
    """Contest when a proof of delivery is present and carries a signature.

    The hand-written rule a domain expert produces without a model.  Correct in
    spirit for the non-receipt cluster, and blind to amount entirely -- so it
    happily spends INR 350 to contest a INR 400 dispute.
    """
    decisions: list[int] = []
    for record in records:
        pod = record.bundle.pod
        has_pod = pod.extraction_status in (
            ExtractionStatus.VERIFIED,
            ExtractionStatus.LOW_CONFIDENCE,
        )
        decisions.append(1 if (has_pod and pod.signature_captured) else 0)
    return np.asarray(decisions, dtype=np.int64)


#: The four comparators, in report order.
BASELINES: tuple[Baseline, ...] = (
    Baseline(
        name="Contest nothing",
        describe="Absorb every chargeback. The merchant default.",
        decide=contest_nothing,
    ),
    Baseline(
        name="Contest everything",
        describe="Fight every dispute. Perfect recall, pays c on every loss.",
        decide=contest_everything,
    ),
    Baseline(
        name=f"Fixed threshold (>= INR {int(FIXED_THRESHOLD_INR):,})",
        describe="Contest above a round rupee cutoff. Strongest non-ML rule.",
        decide=fixed_threshold,
    ),
    Baseline(
        name="Evidence heuristic (POD + signature)",
        describe="Hand-written domain rule. Ignores the amount at stake.",
        decide=evidence_heuristic,
    ),
)
