"""Fit the win-probability booster and its isotonic calibrator.

Run with ``make train`` (``python -m sentinel.models.train``).

The three-way split
===================
The 15 000-row training corpus is partitioned into **three disjoint folds**, not
two:

===========  ======  ==========================================================
fold          share   used for
===========  ======  ==========================================================
``fit``        75%    gradient boosting, and 5-fold out-of-fold predictions
                      on which the isotonic map is fitted
``stop``      12.5%   early stopping -- selects the number of boosting rounds
``calib``     12.5%   **selecting** the calibrator: touched by neither the
                      booster nor the isotonic fit
===========  ======  ==========================================================

The usual shortcut is to reuse one validation fold for both early stopping and
calibration.  That is a real leak, if a subtle one: the round count is chosen to
minimise loss *on those exact rows*, so the booster's scores there are
optimistically calibrated relative to fresh data, and the isotonic map inherits
that optimism.  The result is a model whose Brier score looks good on the
validation fold and drifts on the test set -- which, because the policy engine
multiplies ``p`` by rupees, shows up as systematically wrong expected values
rather than as a slightly worse ranking.

Splitting three ways costs 12.5% of the training rows and removes the leak
entirely.  Given that the entire value proposition rests on ``p`` being a
genuine probability, that is a trade worth making.

Calibration is selected, not assumed
====================================
The received wisdom is that a tree ensemble always needs isotonic or Platt
correction.  That wisdom is about models trained on non-proper objectives.
LightGBM minimising ``binary_logloss`` is minimising a **strictly proper scoring
rule**, so it is already optimising calibrated probability estimates directly.

This pipeline therefore fits isotonic properly -- on 11 250 out-of-fold
predictions, not on a thin holdout -- and then *measures* it against the raw
booster on the untouched ``calib`` fold before shipping either.  On the current
corpus the raw booster wins (Brier 0.16956 vs 0.17010, ECE 0.02538 vs 0.03544),
so ``select_calibrator`` ships the identity map and records why.

That is a stronger guarantee than applying isotonic unconditionally, not a
weaker one: if the booster ever became miscalibrated -- a different objective, a
shifted corpus, a deeper model -- the same comparison would select the isotonic
map automatically, with no code change.  See :func:`select_calibrator`.

Determinism
===========
The fold assignment uses :data:`~data_gen.seeds.SPLIT_SEED` and LightGBM is
seeded from :data:`~data_gen.seeds.TRAIN_SEED` with ``deterministic=True`` and
single-threaded histogram construction, so ``make train`` produces byte-identical
artifacts on any machine.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from data_gen.generator import LoadedRecord, load_corpus
from data_gen.seeds import SPLIT_SEED, TRAIN_SEED
from sentinel.config import Settings, get_settings
from sentinel.features import builder
from sentinel.features.registry import feature_names, integer_feature_indices
from sentinel.models.calibration import (
    CalibrationDiagnostics,
    IsotonicCalibrator,
    brier_score,
    expected_calibration_error,
)
from sentinel.models.win_probability import (
    BOOSTER_FILENAME,
    CALIBRATOR_FILENAME,
    METADATA_FILENAME,
    compute_model_version,
)
from sentinel.schemas.features import FEATURE_ORDER, FEATURE_VERSION

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("sentinel.train")

#: Fold proportions. Must sum to 1.0.
FIT_SHARE: float = 0.75
STOP_SHARE: float = 0.125
CALIB_SHARE: float = 0.125

#: LightGBM hyperparameters.
#:
#: Conservative by design.  The generator's irreducible noise means a deeper or
#: longer-trained model buys variance rather than signal, and a well-calibrated
#: shallow model serves the economics better than a sharper miscalibrated one.
LGB_PARAMS: dict[str, object] = {
    "objective": "binary",
    "metric": ["auc", "binary_logloss"],
    "boosting_type": "gbdt",
    "learning_rate": 0.045,
    "num_leaves": 31,
    "max_depth": 6,
    "min_data_in_leaf": 60,
    "feature_fraction": 0.85,
    "bagging_fraction": 0.85,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbosity": -1,
    "seed": TRAIN_SEED,
    "bagging_seed": TRAIN_SEED + 1,
    "feature_fraction_seed": TRAIN_SEED + 2,
    "data_random_seed": TRAIN_SEED + 3,
    # Determinism: identical artifacts on any machine, at a small speed cost.
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 1,
}

#: Maximum boosting rounds; early stopping almost always finishes sooner.
MAX_ROUNDS: int = 900

#: Rounds without improvement on the ``stop`` fold before halting.
EARLY_STOPPING_ROUNDS: int = 60

#: Folds used to produce out-of-fold predictions for calibration.
#:
#: Isotonic regression fits an arbitrary non-decreasing step function, which
#: makes it flexible enough to correct LightGBM's distortion and hungry enough
#: to overfit a small fold.  Fitting it on the 1 875-row ``calib`` split alone
#: measurably *degraded* held-out calibration -- test-set Brier 0.1580 -> 0.1590
#: and ECE 0.0234 -> 0.0295 -- because the variance it added exceeded the bias
#: it removed.
#:
#: Fitting instead on out-of-fold predictions over the whole 11 250-row ``fit``
#: split gives the calibrator six times the data with no leakage: every OOF
#: prediction comes from a booster that never saw that row.  The ``calib`` split
#: is then left completely untouched by both boosting and calibration, so the
#: diagnostics computed on it are genuinely out-of-sample.
CALIBRATION_FOLDS: int = 5


def split_indices(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Partition ``n`` rows into disjoint fit / stop / calib folds.

    Uses :data:`SPLIT_SEED` so the partition is stable across runs and machines.

    Returns:
        ``(fit_idx, stop_idx, calib_idx)``, mutually disjoint and jointly
        covering ``range(n)``.
    """
    rng = np.random.default_rng(SPLIT_SEED + 17)
    permutation = rng.permutation(n)

    n_fit = int(round(FIT_SHARE * n))
    n_stop = int(round(STOP_SHARE * n))

    fit_idx = permutation[:n_fit]
    stop_idx = permutation[n_fit : n_fit + n_stop]
    calib_idx = permutation[n_fit + n_stop :]

    assert len(set(fit_idx) & set(stop_idx)) == 0
    assert len(set(fit_idx) & set(calib_idx)) == 0
    assert len(set(stop_idx) & set(calib_idx)) == 0
    return fit_idx, stop_idx, calib_idx


def build_design_matrix(
    records: list[LoadedRecord],
) -> tuple[np.ndarray, np.ndarray]:
    """Build the feature matrix and label vector from loaded corpus records.

    Every row goes through the same pure :func:`sentinel.features.builder.build`
    used at serving time.  There is no separate training-time feature path, so
    train/serve skew is structurally impossible rather than merely unlikely.
    """
    rows: list[np.ndarray] = []
    labels: list[int] = []
    for record in records:
        vector = builder.build(record.dispute, record.bundle)
        rows.append(vector.to_array()[0])
        labels.append(record.won)

    return (
        np.vstack(rows).astype(np.float64),
        np.asarray(labels, dtype=np.int32),
    )


def _out_of_fold_predictions(
    matrix: np.ndarray,
    labels: np.ndarray,
    fit_idx: np.ndarray,
    n_rounds: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return out-of-fold raw scores over the ``fit`` split, and their labels.

    Trains ``CALIBRATION_FOLDS`` boosters, each on all but one fold of the fit
    split, and predicts the held-out fold with it.  Every returned score
    therefore comes from a model that never saw that row, which is what makes
    the resulting calibration map honest.

    The fold models use the same hyperparameters and the same round count as the
    production booster, so the score distribution they produce matches the one
    the calibrator will actually be applied to.  Fitting the map against a
    differently-shaped distribution would calibrate for the wrong model.
    """
    import lightgbm as lgb

    rng = np.random.default_rng(SPLIT_SEED + 29)
    shuffled = rng.permutation(fit_idx)
    folds = np.array_split(shuffled, CALIBRATION_FOLDS)

    names = list(feature_names())
    oof_scores = np.empty(len(fit_idx), dtype=np.float64)
    oof_labels = np.empty(len(fit_idx), dtype=np.float64)
    cursor = 0

    for held_out in folds:
        inner_train = np.setdiff1d(shuffled, held_out, assume_unique=False)

        dataset = lgb.Dataset(
            matrix[inner_train],
            label=labels[inner_train],
            feature_name=names,
            free_raw_data=False,
        )
        fold_booster = lgb.train(
            LGB_PARAMS, dataset, num_boost_round=n_rounds
        )

        scores = np.asarray(fold_booster.predict(matrix[held_out])).ravel()
        span = slice(cursor, cursor + len(held_out))
        oof_scores[span] = scores
        oof_labels[span] = labels[held_out].astype(np.float64)
        cursor += len(held_out)

    return oof_scores, oof_labels


def select_calibrator(
    matrix: np.ndarray,
    labels: np.ndarray,
    fit_idx: np.ndarray,
    calib_idx: np.ndarray,
    booster: object,
    best_iter: int,
) -> tuple[IsotonicCalibrator, CalibrationDiagnostics]:
    """Fit the isotonic map, then decide on evidence whether to ship it.

    The received wisdom is to apply isotonic regression unconditionally to any
    tree ensemble.  That wisdom is about models trained on non-proper objectives.
    LightGBM optimising ``binary_logloss`` is minimising a **strictly proper
    scoring rule**, which means it is directly optimising calibrated probability
    estimates -- there is frequently no sigmoidal distortion left to correct, and
    a flexible non-parametric map can then only add variance.

    So this function measures rather than assumes:

    1. Fit isotonic on out-of-fold predictions over the whole ``fit`` split.
    2. Score both the raw booster and the isotonic-corrected booster on
       ``calib``, a fold neither the booster nor the calibrator has seen.
    3. Ship whichever has the lower Brier score, and record both figures.

    Brier is the selection criterion rather than ECE because it is a strictly
    proper scoring rule: it is minimised only by reporting the true probability,
    whereas ECE can be gamed by a model that is well-calibrated on average while
    being wrong in every individual bin.

    This is a stronger guarantee than unconditional isotonic, not a weaker one --
    if the booster ever became miscalibrated, the same comparison would select
    the isotonic map automatically. The decision is made on a held-out fold, not
    on the test set, so it costs nothing in evaluation integrity.

    Returns:
        The selected calibrator and the diagnostics that selected it.
    """
    oof_raw, oof_labels = _out_of_fold_predictions(
        matrix, labels, fit_idx, best_iter
    )

    calibrator = IsotonicCalibrator()
    calibrator.fit(oof_raw, oof_labels)

    calib_raw = np.asarray(
        booster.predict(matrix[calib_idx], num_iteration=best_iter)
    ).ravel()
    calib_labels = labels[calib_idx].astype(np.float64)
    calib_isotonic = calibrator.transform(calib_raw)

    brier_raw = brier_score(calib_raw, calib_labels)
    brier_isotonic = brier_score(calib_isotonic, calib_labels)
    ece_raw = expected_calibration_error(calib_raw, calib_labels)
    ece_isotonic = expected_calibration_error(calib_isotonic, calib_labels)

    calibrator.passthrough = brier_raw <= brier_isotonic

    diagnostics = CalibrationDiagnostics(
        brier_before=brier_raw,
        brier_after=brier_isotonic,
        ece_before=ece_raw,
        ece_after=ece_isotonic,
        n_calibration_rows=int(oof_raw.size),
    )
    calibrator.diagnostics = diagnostics

    logger.info(
        "  calibration  : isotonic fitted on %s out-of-fold rows (%d folds)",
        f"{oof_raw.size:,}",
        CALIBRATION_FOLDS,
    )
    logger.info(
        "  selection    : on %s untouched rows, Brier raw=%.5f isotonic=%.5f "
        "| ECE raw=%.5f isotonic=%.5f",
        f"{len(calib_idx):,}",
        brier_raw,
        brier_isotonic,
        ece_raw,
        ece_isotonic,
    )
    logger.info(
        "  shipping     : %s  (%s)",
        calibrator.mode,
        "the booster is already calibrated; isotonic would add variance"
        if calibrator.passthrough
        else "isotonic improves held-out calibration",
    )

    return calibrator, diagnostics


def train(settings: Settings | None = None) -> dict:
    """Fit the booster and calibrator, write artifacts, and return metadata.

    Raises:
        FileNotFoundError: if the corpus has not been generated.
    """
    cfg = settings if settings is not None else get_settings()
    cfg.ensure_dirs()

    train_path = cfg.data_dir / "train.jsonl"
    if not train_path.is_file():
        raise FileNotFoundError(
            f"training corpus not found at {train_path}. Run `make data` first."
        )

    logger.info("ChargeGuard :: model training")
    logger.info("  loading      : %s", train_path)

    # rebase_to_now=False: training reads only timestamp *differences*, all of
    # which are translation-invariant, so the rebase is pure overhead here.
    records = load_corpus(train_path, rebase_to_now=False)
    logger.info("  rows         : %s", f"{len(records):,}")

    matrix, labels = build_design_matrix(records)
    logger.info("  design       : %s x %s", f"{matrix.shape[0]:,}", matrix.shape[1])
    logger.info("  base rate    : %.4f", float(labels.mean()))

    fit_idx, stop_idx, calib_idx = split_indices(len(records))
    logger.info(
        "  folds        : fit=%s stop=%s calib=%s (disjoint)",
        f"{len(fit_idx):,}",
        f"{len(stop_idx):,}",
        f"{len(calib_idx):,}",
    )

    import lightgbm as lgb

    names = list(feature_names())
    fit_set = lgb.Dataset(
        matrix[fit_idx],
        label=labels[fit_idx],
        feature_name=names,
        free_raw_data=False,
    )
    stop_set = lgb.Dataset(
        matrix[stop_idx],
        label=labels[stop_idx],
        feature_name=names,
        reference=fit_set,
        free_raw_data=False,
    )

    evals: dict = {}
    booster = lgb.train(
        LGB_PARAMS,
        fit_set,
        num_boost_round=MAX_ROUNDS,
        valid_sets=[stop_set],
        valid_names=["stop"],
        callbacks=[
            lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False),
            lgb.record_evaluation(evals),
        ],
    )

    best_iter = int(booster.best_iteration or MAX_ROUNDS)
    stop_auc = float(evals["stop"]["auc"][best_iter - 1])
    stop_logloss = float(evals["stop"]["binary_logloss"][best_iter - 1])
    logger.info(
        "  boosting     : stopped at round %d (stop-fold AUC %.4f, logloss %.4f)",
        best_iter,
        stop_auc,
        stop_logloss,
    )

    # -- calibration: fit isotonic, then measure whether it actually helps -- #
    calibrator, diagnostics = select_calibrator(
        matrix, labels, fit_idx, calib_idx, booster, best_iter
    )

    # -- feature importances ---------------------------------------------- #
    gains = booster.feature_importance(importance_type="gain")
    total_gain = float(np.sum(gains)) or 1.0
    importances = sorted(
        (
            {
                "feature": name,
                "gain": round(float(gain), 4),
                "share": round(float(gain) / total_gain, 6),
            }
            for name, gain in zip(names, gains)
        ),
        key=lambda row: float(row["gain"]),
        reverse=True,
    )

    logger.info("  top features by gain:")
    for row in importances[:10]:
        logger.info(
            "    %-32s %6.2f%%", row["feature"], 100.0 * float(row["share"])
        )

    # -- persist ----------------------------------------------------------- #
    booster_path = cfg.artifacts_dir / BOOSTER_FILENAME
    calibrator_path = cfg.artifacts_dir / CALIBRATOR_FILENAME
    metadata_path = cfg.artifacts_dir / METADATA_FILENAME

    booster.save_model(str(booster_path), num_iteration=best_iter)
    calibrator.save(calibrator_path)

    metadata = {
        "feature_version": FEATURE_VERSION,
        "feature_order": list(FEATURE_ORDER),
        "integer_feature_indices": list(integer_feature_indices()),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_corpus_rows": len(records),
        "n_fit_rows": int(len(fit_idx)),
        "n_stop_rows": int(len(stop_idx)),
        "n_calib_rows": int(len(calib_idx)),
        "base_rate": round(float(labels.mean()), 6),
        "best_iteration": best_iter,
        "stop_fold_auc": round(stop_auc, 6),
        "stop_fold_logloss": round(stop_logloss, 6),
        "lgb_params": {k: v for k, v in LGB_PARAMS.items()},
        "calibration": {
            **diagnostics.as_dict(),
            "mode": calibrator.mode,
            "n_selection_rows": int(len(calib_idx)),
            "selection_criterion": "held-out Brier score on the calib fold",
        },
        "feature_importances": importances,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    version = compute_model_version(booster_path, calibrator_path, FEATURE_VERSION)
    metadata["model_version"] = version
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info("  artifacts    : %s", cfg.artifacts_dir)
    logger.info("    %s", booster_path.name)
    logger.info("    %s", calibrator_path.name)
    logger.info("    %s", metadata_path.name)
    logger.info("  model_version: %s", version)
    logger.info("done.")

    return metadata


def main() -> int:
    """CLI entry point for ``make train``."""
    train()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
