"""Isotonic calibration of the raw model score.

Why this module exists
======================

Almost every classifier in production is used as a **ranking** function: sort by
score, act on the top *k*, and the absolute value of the score never enters an
arithmetic expression.  Under that use, calibration is cosmetic.

ChargeGuard does not use its model that way.  The policy engine computes

.. code-block:: text

    EV_i = p_i * A_i - c
    contest  <=>  p_i >= lambda * c / A_i

``p_i`` is **multiplied by rupees** and **compared against an arithmetic
threshold**.  If the model says 0.30 and the true frequency at that score is
0.55, then on a INR 20 000 dispute we compute an expected value of INR 5 650
when the truth is INR 10 650 -- and, worse, on a INR 1 400 dispute we compare
0.30 against a threshold of 0.30 and land on the wrong side of a decision whose
true expected value was comfortably positive.

An uncalibrated score does not merely make the numbers ugly.  It corrupts
**every threshold comparison in the system**, and it does so in a way that is
invisible in AUC, which is rank-based and completely insensitive to monotone
distortion of the score.  This is why the evaluation harness reports Brier score
and expected calibration error alongside AUC: AUC could be excellent while the
economics were systematically wrong.

Why isotonic rather than Platt
==============================

Platt scaling fits a two-parameter logistic to the scores.  That is the right
choice when the miscalibration is genuinely sigmoidal and data is scarce.
LightGBM's distortion is not sigmoidal -- gradient boosting with early stopping
tends to produce scores that are over-confident in the tails and compressed in
the middle, in a shape that varies with the depth and the number of rounds.

Isotonic regression fits an arbitrary non-decreasing step function, so it can
correct that shape without assuming it.  Its cost is variance: with a small
calibration fold it will overfit, and it cannot extrapolate beyond the range of
scores it saw.  Both are handled here -- the fold is ~1 900 rows, comfortably
above the few-hundred-row regime where isotonic breaks down, and
:meth:`IsotonicCalibrator.transform` clips to [0, 1] and relies on sklearn's
``out_of_bounds="clip"`` so an unseen extreme score maps to the nearest fitted
value rather than to NaN.

Fold discipline
===============

The calibration fold is **disjoint from both the fitting fold and the
early-stopping fold**.  Fitting the calibrator on data the booster trained on
would calibrate against memorised labels and produce a confidently wrong map;
fitting it on the early-stopping fold would be subtler but still leaky, because
the number of boosting rounds was selected against exactly those rows.  See
:func:`sentinel.models.train.split_indices`.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression

#: Filename of the pickled calibrator inside the artifacts directory.
CALIBRATOR_FILENAME: str = "calibrator.pkl"


@dataclass(slots=True)
class CalibrationDiagnostics:
    """Before/after calibration quality, recorded at fit time.

    Written into the model metadata so the report can state what calibration
    actually bought rather than asserting that it helped.
    """

    brier_before: float
    brier_after: float
    ece_before: float
    ece_after: float
    n_calibration_rows: int

    def as_dict(self) -> dict[str, float | int]:
        """JSON-serialisable view for the model metadata file."""
        return {
            "brier_before": round(self.brier_before, 6),
            "brier_after": round(self.brier_after, 6),
            "ece_before": round(self.ece_before, 6),
            "ece_after": round(self.ece_after, 6),
            "n_calibration_rows": self.n_calibration_rows,
        }


def brier_score(probabilities: np.ndarray, outcomes: np.ndarray) -> float:
    """Mean squared error between predicted probabilities and binary outcomes.

    A strictly proper scoring rule: it is minimised only by reporting the true
    probability, so unlike AUC it punishes miscalibration directly.
    """
    return float(np.mean((probabilities - outcomes) ** 2))


def expected_calibration_error(
    probabilities: np.ndarray, outcomes: np.ndarray, n_bins: int = 10
) -> float:
    """Expected calibration error over ``n_bins`` equal-width bins.

    The weighted mean absolute gap between predicted confidence and observed
    frequency.  Empty bins contribute nothing rather than being counted as
    perfectly calibrated, which would flatter a model that never predicts in
    part of the range.
    """
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = len(probabilities)
    if total == 0:
        return 0.0

    error = 0.0
    for i in range(n_bins):
        low, high = edges[i], edges[i + 1]
        # Include the right edge only in the final bin so p=1.0 is counted once.
        if i == n_bins - 1:
            mask = (probabilities >= low) & (probabilities <= high)
        else:
            mask = (probabilities >= low) & (probabilities < high)
        count = int(mask.sum())
        if count == 0:
            continue
        gap = abs(float(probabilities[mask].mean()) - float(outcomes[mask].mean()))
        error += (count / total) * gap
    return float(error)


def reliability_points(
    probabilities: np.ndarray, outcomes: np.ndarray, n_bins: int = 10
) -> list[dict[str, float | int]]:
    """Return reliability-diagram points: mean predicted vs observed per bin.

    Consumed by the frontend's calibration curve.  Empty bins are omitted rather
    than plotted at zero, which would draw a misleading dive to the origin.
    """
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    points: list[dict[str, float | int]] = []

    for i in range(n_bins):
        low, high = edges[i], edges[i + 1]
        if i == n_bins - 1:
            mask = (probabilities >= low) & (probabilities <= high)
        else:
            mask = (probabilities >= low) & (probabilities < high)
        count = int(mask.sum())
        if count == 0:
            continue
        points.append(
            {
                "predicted": round(float(probabilities[mask].mean()), 6),
                "observed": round(float(outcomes[mask].mean()), 6),
                "count": count,
            }
        )
    return points


class IsotonicCalibrator:
    """Maps raw model scores onto calibrated probabilities.

    Wraps :class:`sklearn.isotonic.IsotonicRegression` with the clipping,
    persistence, and diagnostics the policy engine needs.  The engine consumes
    the output of :meth:`transform` as a genuine probability, so this class is
    responsible for the guarantee that its output is in [0, 1] and monotone in
    the raw score.

    Passthrough mode
    ----------------
    The calibrator can be put in ``passthrough`` mode, in which :meth:`transform`
    returns the raw score unchanged (clipped to [0, 1]).  That mode is selected
    by :func:`sentinel.models.train.select_calibrator`, which fits the isotonic
    map, measures both options on a fold that neither the booster nor the
    calibrator has seen, and ships whichever is better calibrated.

    This is a *stronger* guarantee than unconditionally applying isotonic, not a
    weaker one.  Unconditional application assumes the correction helps; the
    selection measures it.  On the shipped corpus the raw booster wins, because
    LightGBM optimising binary logloss -- a strictly proper scoring rule -- is
    already producing calibrated probabilities, leaving isotonic nothing to
    correct and only variance to add.  If the corpus or the objective changed
    such that the booster became miscalibrated, the same comparison would select
    isotonic automatically.
    """

    def __init__(self) -> None:
        self._model = IsotonicRegression(
            y_min=0.0,
            y_max=1.0,
            increasing=True,
            # An unseen extreme score maps to the nearest fitted value rather
            # than to NaN, which would propagate into an EV computation.
            out_of_bounds="clip",
        )
        self._fitted: bool = False
        self.passthrough: bool = False
        """When True, :meth:`transform` returns the raw score unchanged.
        Set by the held-out selection in ``train.select_calibrator``."""
        self.diagnostics: CalibrationDiagnostics | None = None

    @property
    def is_fitted(self) -> bool:
        """True once :meth:`fit` has run."""
        return self._fitted

    @property
    def mode(self) -> str:
        """``"isotonic"`` or ``"identity"`` -- which map is actually applied.

        Stamped into the model metadata and surfaced in the evaluation report,
        so a reader is never left guessing whether the calibration step shipped.
        """
        return "identity" if self.passthrough else "isotonic"

    def fit(
        self, raw_scores: np.ndarray, outcomes: np.ndarray, n_bins: int = 10
    ) -> CalibrationDiagnostics:
        """Fit on a held-out calibration fold and record before/after quality.

        Args:
            raw_scores: Uncalibrated model outputs for the calibration fold.
            outcomes: Binary realised outcomes for the same rows.
            n_bins: Bin count for the ECE diagnostic.

        Returns:
            Diagnostics comparing calibration quality before and after.

        Raises:
            ValueError: on empty or mismatched inputs.
        """
        raw = np.asarray(raw_scores, dtype=np.float64).ravel()
        y = np.asarray(outcomes, dtype=np.float64).ravel()

        if raw.size == 0:
            raise ValueError("cannot fit a calibrator on an empty fold")
        if raw.shape != y.shape:
            raise ValueError(
                f"score/outcome shape mismatch: {raw.shape} vs {y.shape}"
            )

        self._model.fit(raw, y)
        self._fitted = True

        calibrated = self.transform(raw)
        self.diagnostics = CalibrationDiagnostics(
            brier_before=brier_score(raw, y),
            brier_after=brier_score(calibrated, y),
            ece_before=expected_calibration_error(raw, y, n_bins),
            ece_after=expected_calibration_error(calibrated, y, n_bins),
            n_calibration_rows=int(raw.size),
        )
        return self.diagnostics

    def transform(self, raw_scores: np.ndarray) -> np.ndarray:
        """Map raw scores to calibrated probabilities, clipped to [0, 1].

        Raises:
            RuntimeError: if called before :meth:`fit`. Silently passing raw
                scores through would hand the policy engine an uncalibrated
                number wearing the name of a probability, which is precisely the
                failure this module exists to prevent.
        """
        if not self._fitted:
            raise RuntimeError(
                "IsotonicCalibrator.transform called before fit. The policy "
                "engine treats its input as a genuine probability; passing an "
                "uncalibrated score through would corrupt every threshold."
            )
        raw = np.asarray(raw_scores, dtype=np.float64).ravel()
        if self.passthrough:
            # Selected, not assumed: the isotonic map was fitted and measured
            # against the identity on an untouched fold, and lost. See the
            # class docstring.
            return np.clip(raw, 0.0, 1.0)
        return np.clip(self._model.predict(raw), 0.0, 1.0)

    def transform_isotonic(self, raw_scores: np.ndarray) -> np.ndarray:
        """Apply the fitted isotonic map regardless of passthrough mode.

        **Diagnostics only.** The evaluation harness uses this to report the
        counterfactual -- what calibration *would* have done on the test set --
        alongside what actually shipped. The policy engine never sees this
        output; it consumes :meth:`transform`, which honours the selection.
        """
        if not self._fitted:
            raise RuntimeError("transform_isotonic called before fit")
        raw = np.asarray(raw_scores, dtype=np.float64).ravel()
        return np.clip(self._model.predict(raw), 0.0, 1.0)

    def transform_one(self, raw_score: float) -> float:
        """Calibrate a single score. The serving path."""
        return float(self.transform(np.asarray([raw_score], dtype=np.float64))[0])

    def save(self, path: Path) -> None:
        """Pickle the fitted calibrator to ``path``."""
        if not self._fitted:
            raise RuntimeError("refusing to persist an unfitted calibrator")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump(
                {
                    "model": self._model,
                    "diagnostics": self.diagnostics,
                    "passthrough": self.passthrough,
                },
                handle,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

    @classmethod
    def load(cls, path: Path) -> IsotonicCalibrator:
        """Load a pickled calibrator from ``path``.

        Raises:
            FileNotFoundError: if the artifact is missing. Callers must handle
                this explicitly rather than falling back to raw scores.
        """
        if not path.is_file():
            raise FileNotFoundError(
                f"calibrator artifact not found at {path}. Run `make train`."
            )
        with path.open("rb") as handle:
            payload = pickle.load(handle)

        instance = cls()
        instance._model = payload["model"]
        instance.diagnostics = payload.get("diagnostics")
        instance.passthrough = bool(payload.get("passthrough", False))
        instance._fitted = True
        return instance


class IdentityCalibrator(IsotonicCalibrator):
    """Pass-through calibrator used only to demonstrate what calibration buys.

    The simulator's "raw vs calibrated" toggle needs both numbers side by side.
    This subclass provides the raw one through the same interface without
    letting the serving path accidentally use it: the policy engine is only ever
    handed the output of a fitted :class:`IsotonicCalibrator`.
    """

    def __init__(self) -> None:
        super().__init__()
        self._fitted = True

    def transform(self, raw_scores: np.ndarray) -> np.ndarray:
        """Return the raw scores unchanged, clipped to [0, 1]."""
        return np.clip(
            np.asarray(raw_scores, dtype=np.float64).ravel(), 0.0, 1.0
        )
