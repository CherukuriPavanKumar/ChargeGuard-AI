"""Serving-side win-probability estimation.

What this module is
===================
A function from :class:`~sentinel.schemas.features.FeatureVector` to a float in
[0, 1].  That is the whole contract.

What this module is **not**
===========================
A decision maker.  It returns a number and has no opinion about what to do with
it.  ``Decision`` is not importable from here and is never constructed here --
see INVARIANT 1 in :mod:`sentinel.policy.engine`.

Serving constraints
===================
Inference is pure CPU tree traversal against an in-process LightGBM booster.
There is no network call, no database read, and no feature-store lookup on the
scoring path.  That is what makes the p95 latency budget of 200 ms achievable
with three orders of magnitude to spare, and it is why
``POST /v1/disputes/score`` can be synchronous while packet generation is not.

Version identity
================
``model_version`` is derived from the SHA-256 of the booster text plus the
calibrator pickle plus the feature version, truncated to 12 hex characters.
It is stamped onto every :class:`~sentinel.schemas.decision.Decision`.  Two
decisions carrying the same ``model_version`` were produced by byte-identical
artifacts; two carrying different versions were not, regardless of what any
filename or timestamp claims.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import numpy as np

from sentinel.config import Settings, get_settings
from sentinel.models.calibration import IsotonicCalibrator
from sentinel.schemas.features import FEATURE_ORDER, FeatureVector

logger = logging.getLogger(__name__)

#: Artifact filenames inside ``settings.artifacts_dir``.
BOOSTER_FILENAME: str = "booster.txt"
CALIBRATOR_FILENAME: str = "calibrator.pkl"
METADATA_FILENAME: str = "model_meta.json"


class ModelArtifactsMissing(RuntimeError):
    """Raised when the model artifacts have not been built.

    Deliberately fatal rather than degrading to a constant score.  A silent
    fallback would produce plausible-looking decisions from a model that does
    not exist, and the audit trail would record a ``model_version`` for
    something that never ran.
    """


def _sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file's contents."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_model_version(
    booster_path: Path, calibrator_path: Path, feature_version: str
) -> str:
    """Derive a content-addressed version string for the artifact pair."""
    combined = hashlib.sha256()
    combined.update(_sha256_file(booster_path).encode("ascii"))
    combined.update(_sha256_file(calibrator_path).encode("ascii"))
    combined.update(feature_version.encode("ascii"))
    return f"lgbm-{feature_version}-{combined.hexdigest()[:12]}"


class WinProbabilityModel:
    """Calibrated ``P(win | evidence)`` estimator.

    Load once at process start and reuse; construction reads two files from disk
    and is not on the latency budget, whereas :meth:`predict_proba` is.
    """

    def __init__(
        self,
        booster: object,
        calibrator: IsotonicCalibrator,
        model_version: str,
        metadata: dict | None = None,
    ) -> None:
        self._booster = booster
        self._calibrator = calibrator
        self.model_version = model_version
        self.metadata: dict = metadata or {}

    # ------------------------------------------------------------------ #
    # Construction                                                       #
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, settings: Settings | None = None) -> WinProbabilityModel:
        """Load the trained artifacts from ``settings.artifacts_dir``.

        Raises:
            ModelArtifactsMissing: if either artifact is absent, with the
                command needed to produce them.
        """
        cfg = settings if settings is not None else get_settings()
        artifacts = cfg.artifacts_dir

        booster_path = artifacts / BOOSTER_FILENAME
        calibrator_path = artifacts / CALIBRATOR_FILENAME

        missing = [
            str(p) for p in (booster_path, calibrator_path) if not p.is_file()
        ]
        if missing:
            raise ModelArtifactsMissing(
                "model artifacts not found: "
                + ", ".join(missing)
                + ". Run `make train` (which requires `make data` first)."
            )

        try:
            import lightgbm as lgb
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ModelArtifactsMissing(
                f"lightgbm is not installed: {exc}. Run `make install`."
            ) from exc

        booster = lgb.Booster(model_file=str(booster_path))
        calibrator = IsotonicCalibrator.load(calibrator_path)

        metadata_path = artifacts / METADATA_FILENAME
        metadata: dict = {}
        if metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        version = compute_model_version(
            booster_path, calibrator_path, metadata.get("feature_version", "unknown")
        )

        stored_order = metadata.get("feature_order")
        if stored_order is not None and tuple(stored_order) != FEATURE_ORDER:
            # The single most dangerous silent failure in production ML: the
            # matrix still has the right shape, so nothing raises, and every
            # prediction is scored against the wrong columns.
            raise ModelArtifactsMissing(
                "feature order in the trained artifact does not match the "
                "current feature registry. The model would score the wrong "
                "columns. Retrain with `make train`."
            )

        logger.info("loaded win-probability model %s", version)
        return cls(booster, calibrator, version, metadata)

    # ------------------------------------------------------------------ #
    # Inference                                                          #
    # ------------------------------------------------------------------ #

    def raw_score(self, features: FeatureVector) -> float:
        """Return the uncalibrated booster output.

        Exposed for the simulator's raw-vs-calibrated comparison and for the
        evaluation harness's calibration diagnostics.  **Never** passed to the
        policy engine: it is not a probability.
        """
        matrix = features.to_array()
        prediction = self._booster.predict(matrix, num_iteration=self._best_iteration())
        return float(np.asarray(prediction).ravel()[0])

    def predict_proba(self, features: FeatureVector) -> float:
        """Return the calibrated ``P(win)`` for one dispute.

        This is the only number the policy engine receives from the model layer.
        """
        return self._calibrator.transform_one(self.raw_score(features))

    def predict_proba_batch(self, vectors: list[FeatureVector]) -> np.ndarray:
        """Vectorised calibrated prediction for many disputes.

        Used by the evaluation harness, where per-row Python overhead over 5 000
        rows would otherwise dominate the runtime.  Numerically identical to
        calling :meth:`predict_proba` in a loop.
        """
        if not vectors:
            return np.asarray([], dtype=np.float64)

        matrix = np.vstack([v.to_array() for v in vectors])
        raw = np.asarray(
            self._booster.predict(matrix, num_iteration=self._best_iteration())
        ).ravel()
        return self._calibrator.transform(raw)

    def raw_score_batch(self, vectors: list[FeatureVector]) -> np.ndarray:
        """Vectorised *uncalibrated* prediction, for calibration diagnostics."""
        if not vectors:
            return np.asarray([], dtype=np.float64)
        matrix = np.vstack([v.to_array() for v in vectors])
        return np.asarray(
            self._booster.predict(matrix, num_iteration=self._best_iteration())
        ).ravel()

    def isotonic_counterfactual(self, features: FeatureVector) -> float:
        """Apply the isotonic map to one vector even if the identity shipped.

        **Diagnostics only.** Powers the simulator's calibration toggle, which
        shows what the fitted isotonic map *would* have produced. Never reaches
        the policy engine.
        """
        return float(
            self._calibrator.transform_isotonic(
                np.asarray([self.raw_score(features)], dtype=np.float64)
            )[0]
        )

    def isotonic_counterfactual_batch(
        self, vectors: list[FeatureVector]
    ) -> np.ndarray:
        """Apply the isotonic map even if the identity was the one shipped.

        **Diagnostics only**, for the evaluation harness's calibration section.
        Never reaches the policy engine.
        """
        if not vectors:
            return np.asarray([], dtype=np.float64)
        return self._calibrator.transform_isotonic(self.raw_score_batch(vectors))

    @property
    def calibration_mode(self) -> str:
        """``"isotonic"`` or ``"identity"`` -- which map is actually applied."""
        return self._calibrator.mode

    def _best_iteration(self) -> int | None:
        """Return the early-stopped iteration count, or None for all rounds."""
        best = getattr(self._booster, "best_iteration", None)
        if isinstance(best, int) and best > 0:
            return best
        return None

    # ------------------------------------------------------------------ #
    # Introspection                                                      #
    # ------------------------------------------------------------------ #

    def feature_importances(self, top_k: int = 15) -> list[dict[str, float | str]]:
        """Return the top ``top_k`` features by total split gain.

        Gain rather than split count: split count over-credits high-cardinality
        continuous features that get chopped repeatedly for small returns.
        """
        try:
            gains = self._booster.feature_importance(importance_type="gain")
        except Exception:  # pragma: no cover - defensive
            return []

        names = self._booster.feature_name()
        total = float(np.sum(gains)) or 1.0
        ranked = sorted(
            (
                {
                    "feature": str(name),
                    "gain": float(gain),
                    "share": round(float(gain) / total, 6),
                }
                for name, gain in zip(names, gains)
            ),
            key=lambda row: float(row["gain"]),
            reverse=True,
        )
        return ranked[:top_k]

    def describe(self) -> dict:
        """Return a JSON-serialisable summary for ``/health`` and the report."""
        return {
            "model_version": self.model_version,
            "feature_version": self.metadata.get("feature_version", "unknown"),
            "n_features": len(FEATURE_ORDER),
            "trained_at": self.metadata.get("trained_at"),
            "n_train_rows": self.metadata.get("n_fit_rows"),
            "best_iteration": self._best_iteration(),
            "calibration": self.metadata.get("calibration", {}),
        }
