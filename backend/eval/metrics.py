"""Classifier metrics for the held-out evaluation.

Two families of number appear here, and conflating them is the mistake this
module is arranged to prevent.

**Discrimination** -- ROC-AUC and PR-AUC -- asks whether the model *ranks*
winnable disputes above unwinnable ones.  It is invariant to any monotone
transformation of the score.  A model with excellent AUC can be arbitrarily
miscalibrated.

**Calibration** -- Brier score and expected calibration error -- asks whether a
score of 0.30 actually corresponds to a 30% win rate.  This is the property the
policy engine depends on, because it multiplies ``p`` by rupees.

ChargeGuard reports both, and the report says plainly which one the economics rest
on.  A submission that showed only AUC would be hiding the number that matters.

The precision/recall framing
============================
``precision`` and ``recall`` are computed on the **decision** ``d_i``, not on a
thresholded score:

* precision = P(won | we contested) -- of the representments we filed, how many
  succeeded;
* recall = P(we contested | winnable) -- of the disputes we could have won, how
  many did we actually fight for.

Given the FN/FP asymmetry documented in :mod:`sentinel.policy.economics`, high
recall at moderate precision is the *correct* operating point, not a defect.
Reading these two numbers the way one would read them in a fraud-blocking system
inverts the economics.
"""

from __future__ import annotations

import numpy as np

#: Bin count for the expected-calibration-error and reliability computations.
DEFAULT_BINS: int = 10


def confusion_matrix(decisions: np.ndarray, outcomes: np.ndarray) -> dict[str, int]:
    """Return the 2x2 confusion counts for contest-vs-win.

    Naming follows the economics, not the usual ML convention:

    * ``tp`` -- contested and won: the money-making case.
    * ``fp`` -- contested and lost: costs ``c``.
    * ``fn`` -- accepted but winnable: costs ``A_i - c``. The expensive error.
    * ``tn`` -- accepted and unwinnable: correct, and free.
    """
    d = np.asarray(decisions, dtype=np.int64)
    w = np.asarray(outcomes, dtype=np.int64)
    return {
        "tp": int(np.sum((d == 1) & (w == 1))),
        "fp": int(np.sum((d == 1) & (w == 0))),
        "fn": int(np.sum((d == 0) & (w == 1))),
        "tn": int(np.sum((d == 0) & (w == 0))),
    }


def precision_recall_f1(
    decisions: np.ndarray, outcomes: np.ndarray
) -> tuple[float, float, float]:
    """Return ``(precision, recall, f1)`` on the realised decisions.

    Each is defined as 0.0 when its denominator is empty, which is the honest
    reading: a policy that contested nothing has no precision to report, and
    claiming 1.0 would flatter it.
    """
    matrix = confusion_matrix(decisions, outcomes)
    tp, fp, fn = matrix["tp"], matrix["fp"], matrix["fn"]

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return float(precision), float(recall), float(f1)


def roc_auc(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    """Area under the ROC curve, computed via the Mann-Whitney U statistic.

    Implemented with rank averaging rather than by integrating a sampled curve,
    so tied scores are handled exactly.  Returns 0.5 when one class is absent,
    the value of a coin flip.
    """
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(outcomes, dtype=np.int64)

    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    if n_pos == 0 or n_neg == 0:
        return 0.5

    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=np.float64)
    ranks[order] = np.arange(1, len(p) + 1, dtype=np.float64)

    # Average ranks within tie groups so ties contribute 0.5 rather than 0 or 1.
    sorted_scores = p[order]
    i = 0
    while i < len(sorted_scores):
        j = i
        while j + 1 < len(sorted_scores) and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        if j > i:
            mean_rank = (i + j + 2) / 2.0
            ranks[order[i : j + 1]] = mean_rank
        i = j + 1

    rank_sum_pos = float(np.sum(ranks[y == 1]))
    u = rank_sum_pos - n_pos * (n_pos + 1) / 2.0
    return float(u / (n_pos * n_neg))


def precision_recall_curve(
    probabilities: np.ndarray, outcomes: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(precision, recall)`` arrays swept over every distinct threshold."""
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(outcomes, dtype=np.int64)

    order = np.argsort(-p, kind="mergesort")
    y_sorted = y[order]

    tp = np.cumsum(y_sorted == 1).astype(np.float64)
    fp = np.cumsum(y_sorted == 0).astype(np.float64)
    total_pos = float(np.sum(y == 1))

    precision = np.divide(
        tp, tp + fp, out=np.zeros_like(tp), where=(tp + fp) > 0
    )
    recall = tp / total_pos if total_pos > 0 else np.zeros_like(tp)
    return precision, recall


def pr_auc(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    """Average precision: the step-wise integral of precision over recall.

    Computed as ``sum_k P(k) * (R(k) - R(k-1))`` rather than by trapezoidal
    interpolation, which is known to be optimistically biased on PR curves.
    """
    y = np.asarray(outcomes, dtype=np.int64)
    if int(np.sum(y == 1)) == 0:
        return 0.0

    precision, recall = precision_recall_curve(probabilities, y)
    recall_prev = np.concatenate(([0.0], recall[:-1]))
    return float(np.sum(precision * (recall - recall_prev)))


def brier_score(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    """Mean squared error of the probabilities. A strictly proper scoring rule.

    Lower is better. The base-rate reference is ``b * (1 - b)``: a model that
    always predicts the base rate ``b`` scores exactly that, so any Brier score
    above it means the model is worse than a constant.
    """
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(outcomes, dtype=np.float64)
    return float(np.mean((p - y) ** 2))


def _bin_masks(
    probabilities: np.ndarray, n_bins: int
) -> list[tuple[float, float, np.ndarray]]:
    """Return ``(low, high, mask)`` per equal-width bin over [0, 1]."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out: list[tuple[float, float, np.ndarray]] = []
    for i in range(n_bins):
        low, high = float(edges[i]), float(edges[i + 1])
        if i == n_bins - 1:
            mask = (probabilities >= low) & (probabilities <= high)
        else:
            mask = (probabilities >= low) & (probabilities < high)
        out.append((low, high, mask))
    return out


def expected_calibration_error(
    probabilities: np.ndarray, outcomes: np.ndarray, n_bins: int = DEFAULT_BINS
) -> float:
    """Weighted mean absolute gap between confidence and observed frequency.

    Empty bins are skipped rather than scored as perfect, which would flatter a
    model that never predicts in part of the range.
    """
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(outcomes, dtype=np.float64)
    total = len(p)
    if total == 0:
        return 0.0

    error = 0.0
    for _low, _high, mask in _bin_masks(p, n_bins):
        count = int(mask.sum())
        if count == 0:
            continue
        gap = abs(float(p[mask].mean()) - float(y[mask].mean()))
        error += (count / total) * gap
    return float(error)


def reliability_curve(
    probabilities: np.ndarray, outcomes: np.ndarray, n_bins: int = DEFAULT_BINS
) -> list[dict[str, float | int]]:
    """Reliability-diagram points consumed by the frontend calibration chart.

    Each point is ``{"predicted", "observed", "count"}``.  Empty bins are
    omitted, so the plotted curve never dives to the origin on no data.
    """
    p = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(outcomes, dtype=np.float64)

    points: list[dict[str, float | int]] = []
    for _low, _high, mask in _bin_masks(p, n_bins):
        count = int(mask.sum())
        if count == 0:
            continue
        points.append(
            {
                "predicted": round(float(p[mask].mean()), 6),
                "observed": round(float(y[mask].mean()), 6),
                "count": count,
            }
        )
    return points


def classifier_report(
    probabilities: np.ndarray,
    decisions: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = DEFAULT_BINS,
) -> dict[str, float]:
    """Return the full classifier block of ``metrics.json``."""
    precision, recall, f1 = precision_recall_f1(decisions, outcomes)
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "pr_auc": round(pr_auc(probabilities, outcomes), 6),
        "roc_auc": round(roc_auc(probabilities, outcomes), 6),
        "brier": round(brier_score(probabilities, outcomes), 6),
        "ece": round(expected_calibration_error(probabilities, outcomes, n_bins), 6),
    }


def latency_histogram(
    samples_ms: np.ndarray, n_bins: int = 28
) -> list[dict[str, float | int]]:
    """Bucket latency samples into a histogram for the dashboard.

    Emitted alongside the percentiles because the dashboard plots a
    *distribution*, and reconstructing one from three percentiles would be
    fabrication -- p50/p95/p99 are consistent with infinitely many shapes, and
    the interesting feature of a latency distribution is usually its right tail,
    which those three numbers describe least well.

    Bin edges are linear between the observed min and max rather than
    logarithmic: this path has no multi-order-of-magnitude spread to compress,
    and a log axis on a tight distribution reads as if it were hiding something.
    """
    arr = np.asarray(samples_ms, dtype=np.float64)
    if arr.size == 0:
        return []

    low, high = float(arr.min()), float(arr.max())
    if high <= low:
        # Degenerate: every sample identical. One bin is the honest rendering.
        return [{"bin_start": low, "bin_end": low, "count": int(arr.size)}]

    counts, edges = np.histogram(arr, bins=n_bins, range=(low, high))
    return [
        {
            "bin_start": round(float(edges[i]), 4),
            "bin_end": round(float(edges[i + 1]), 4),
            "bin_mid": round(float((edges[i] + edges[i + 1]) / 2), 4),
            "count": int(counts[i]),
        }
        for i in range(len(counts))
    ]


def latency_percentiles(samples_ms: np.ndarray) -> dict[str, float]:
    """Return p50/p95/p99 and the sample count from a latency sample.

    Uses linear interpolation between order statistics, matching what a
    monitoring system would report.
    """
    arr = np.asarray(samples_ms, dtype=np.float64)
    if arr.size == 0:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "n": 0}
    return {
        "p50": round(float(np.percentile(arr, 50)), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
        "p99": round(float(np.percentile(arr, 99)), 4),
        "n": int(arr.size),
    }
