"""Frozen seeds and the corpus time anchor.

INVARIANT 4 (determinism): a judge running ``make all`` on a clean machine gets
byte-identical data, an identical train/test split, and identical metrics.  That
requires every stochastic step to draw from a seed committed to this file, and
it requires the corpus to have no dependence on the wall clock.

Seed discipline
---------------
Each generation stage gets its own seed rather than sharing one global RNG.
Sharing a single stream would couple the stages: adding one extra draw in the
POD renderer would shift every subsequent dispute's amount, and the metrics
would move for a reason unrelated to the change.  Independent streams mean a
change to one stage leaves the others bit-identical.

The time anchor
---------------
``CORPUS_EPOCH`` is the frozen instant that stands in for "now" at generation
time.  Every timestamp in the corpus is computed as an offset from it, so the
corpus is fully deterministic.

At load time :func:`data_gen.generator.load_corpus` rebases the corpus by a
rigid translation of ``now - CORPUS_EPOCH`` applied to *every* timestamp.  This
is safe for reproducibility because every feature the model sees is a
*difference* of two timestamps, and differences are invariant under translation:
``window_hours``, ``account_age_days``, ``login_to_order_minutes`` and
``delivery_lag_hours`` are numerically identical before and after.

The one quantity that is not translation-invariant is
``DisputeEvent.hours_remaining``, which is measured against the wall clock and
is read by exactly one consumer: ``policy.gates.expired_window_gate``.  Rebasing
is what makes that gate meaningful -- without it, a corpus generated in the past
would show every dispute as expired, the gate would fire on 100% of rows, and
the evaluation would be worthless.  Because the offset is applied uniformly, the
*fraction* of expired disputes is fixed by the generator (see
``EXPIRED_FRACTION``) and does not drift with the date on which the harness runs.
"""

from __future__ import annotations

from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# Seeds -- one independent stream per stage                                    #
# --------------------------------------------------------------------------- #

#: Root seed. Every other seed is derived from it so the whole corpus can be
#: re-rolled by changing one number, while stages stay mutually independent.
MASTER_SEED: int = 20_260_227

#: Dispute events: reason codes, amounts, networks, timestamps.
DISPUTE_SEED: int = MASTER_SEED + 101

#: The latent winnability process and the realised binary outcomes.
LATENT_SEED: int = MASTER_SEED + 202

#: Observation noise: OCR degradation, missingness, label noise.
OBSERVATION_SEED: int = MASTER_SEED + 303

#: Identity synthesis: names, addresses, devices, IPs, user agents.
IDENTITY_SEED: int = MASTER_SEED + 404

#: Train/test partition. Independent of generation so the split is stable even
#: if the corpus is regenerated with different content.
SPLIT_SEED: int = MASTER_SEED + 505

#: Proof-of-delivery image rendering: fonts, rotation, blur, occlusion.
POD_RENDER_SEED: int = MASTER_SEED + 606

#: LightGBM's internal bagging and feature sampling.
TRAIN_SEED: int = MASTER_SEED + 707

#: Latency benchmark sampling in the evaluation harness.
BENCH_SEED: int = MASTER_SEED + 808


# --------------------------------------------------------------------------- #
# Time anchor                                                                  #
# --------------------------------------------------------------------------- #

#: The frozen "now" of the corpus. Every generated timestamp is an offset from
#: this instant. Chosen as a fixed UTC midnight so it carries no local-timezone
#: or DST ambiguity.
CORPUS_EPOCH: datetime = datetime(2026, 2, 27, 0, 0, 0, tzinfo=timezone.utc)

#: Fraction of disputes whose representment window has already closed at the
#: anchor. Fixed here rather than emerging from the timestamp distribution, so
#: ``expired_window_gate`` has a known, stable activation rate in the report.
EXPIRED_FRACTION: float = 0.02


def stage_seed(name: str) -> int:
    """Return a stable seed for an ad-hoc stage not listed above.

    Derived from the master seed and the stage name so that a new stage cannot
    collide with an existing stream, and so that adding one does not perturb any
    other.  Uses a fixed FNV-1a hash rather than :func:`hash`, whose output is
    randomised per process under PYTHONHASHSEED.
    """
    h = 0x811C9DC5
    for byte in name.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return (MASTER_SEED ^ h) & 0x7FFFFFFF


#: Every seed exposed for the reproducibility banner in ``REPORT.md``.
ALL_SEEDS: dict[str, int] = {
    "MASTER_SEED": MASTER_SEED,
    "DISPUTE_SEED": DISPUTE_SEED,
    "LATENT_SEED": LATENT_SEED,
    "OBSERVATION_SEED": OBSERVATION_SEED,
    "IDENTITY_SEED": IDENTITY_SEED,
    "SPLIT_SEED": SPLIT_SEED,
    "POD_RENDER_SEED": POD_RENDER_SEED,
    "TRAIN_SEED": TRAIN_SEED,
    "BENCH_SEED": BENCH_SEED,
}
