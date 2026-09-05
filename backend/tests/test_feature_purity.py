"""INVARIANT 2: ``features/builder.py`` performs no I/O.

Two independent enforcement mechanisms, because each catches what the other
misses:

**Static** -- AST inspection for forbidden imports and forbidden call names.
Catches a clock read on a branch that no test happens to exercise.

**Behavioural** -- calling ``build()`` repeatedly on identical inputs and
asserting bit-identical output. Catches impurity that arrives through a
dependency rather than through a direct call.

Why this invariant is worth a whole test file
---------------------------------------------
Train/serve skew is the most common way a production ML system degrades
silently. If the builder could read a clock, a feature like "hours since the
dispute was raised" would mean one thing when the training matrix was built and
a different thing at scoring time. Nothing raises. Nothing logs. The model just
gets quietly worse.

Purity makes that failure mode structurally impossible rather than merely
unlikely, and these tests are what keep it that way.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from sentinel.features import builder
from sentinel.features.registry import REGISTRY, feature_names
from sentinel.schemas.features import FEATURE_ORDER, FEATURE_VERSION

BUILDER_PATH = Path(builder.__file__).resolve()

#: Modules the builder may not import. Each is an I/O or nondeterminism vector.
#:
#: ``datetime`` is deliberately absent: the builder imports ``timezone`` from it,
#: which is a constant offset object, not a clock. The clock *functions* are
#: blocked by :data:`FORBIDDEN_CALLS` instead, which is the precise restriction.
FORBIDDEN_IMPORTS = frozenset(
    {
        "random",
        "os",
        "sys",
        "socket",
        "subprocess",
        "pathlib",
        "shutil",
        "tempfile",
        "requests",
        "httpx",
        "urllib",
        "urllib3",
        "aiohttp",
        "time",
        "sqlite3",
        "pickle",
        "io",
        "logging",
    }
)

#: Call names the builder may not use, whatever they are called on.
FORBIDDEN_CALLS = frozenset(
    {
        "now",
        "utcnow",
        "today",
        "fromtimestamp",
        "open",
        "input",
        "time",
        "monotonic",
        "perf_counter",
        "random",
        "uniform",
        "randint",
        "choice",
        "shuffle",
        "seed",
        "getenv",
        "environ",
        "urlopen",
        "get",
        "post",
        "read_text",
        "write_text",
    }
)


def _builder_tree() -> tuple[ast.Module, str]:
    """Parse the builder module."""
    source = BUILDER_PATH.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(BUILDER_PATH)), source


class TestStaticPurity:
    def test_no_forbidden_imports(self):
        """The builder may not import an I/O or randomness module."""
        tree, _ = _builder_tree()
        offenders: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in FORBIDDEN_IMPORTS:
                        offenders.append(f"line {node.lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root in FORBIDDEN_IMPORTS:
                    offenders.append(f"line {node.lineno}: from {node.module} import ...")

        assert not offenders, (
            "features/builder.py must remain pure. Forbidden imports:\n  "
            + "\n  ".join(offenders)
        )

    def test_no_forbidden_calls(self):
        """No clock reads, no randomness, no file handles.

        Checks the *called name* rather than the full dotted path, so
        ``datetime.now()``, ``dt.now()`` and a locally-aliased ``now()`` are all
        caught by the same rule.
        """
        tree, source = _builder_tree()
        offenders: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            called: str | None = None
            if isinstance(node.func, ast.Name):
                called = node.func.id
            elif isinstance(node.func, ast.Attribute):
                called = node.func.attr

            if called in FORBIDDEN_CALLS:
                segment = ast.get_source_segment(source, node) or called
                offenders.append(f"line {node.lineno}: {segment[:70]}")

        assert not offenders, (
            "features/builder.py must not perform I/O or read a clock. Found:\n  "
            + "\n  ".join(offenders)
        )

    def test_timezone_import_is_the_only_datetime_dependency(self):
        """The builder may import ``timezone`` (a constant) and nothing else clocky.

        Documents the one deliberate exception so a reader does not have to
        wonder whether ``from datetime import ...`` slipped through.
        """
        tree, _ = _builder_tree()
        imported: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "datetime":
                imported |= {alias.name for alias in node.names}

        assert imported <= {"datetime", "timezone"}, (
            f"builder imports {sorted(imported)} from datetime; only the "
            f"``timezone`` constant and the ``datetime`` type are permitted"
        )

    def test_no_global_mutable_state(self):
        """Module-level names must be constants, not mutable containers.

        A module-level list or dict is a place for state to accumulate between
        calls, which would break determinism without any forbidden call
        appearing anywhere.
        """
        tree, _ = _builder_tree()

        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if isinstance(value, (ast.List, ast.Dict, ast.Set)):
                    pytest.fail(
                        f"line {node.lineno}: module-level mutable container in "
                        f"features/builder.py; use a tuple or frozenset"
                    )


class TestBehaviouralPurity:
    def test_repeated_calls_produce_identical_output(
        self, base_dispute, base_bundle
    ):
        """**The behavioural half of INVARIANT 2.** Same input, same output."""
        first = builder.build(base_dispute, base_bundle)
        second = builder.build(base_dispute, base_bundle)

        assert first == second
        assert first.to_flat_dict() == second.to_flat_dict()
        np.testing.assert_array_equal(first.to_array(), second.to_array())

    def test_output_is_stable_across_many_calls(self, base_dispute, base_bundle):
        """Twenty calls, no drift. Catches slow accumulation, not just a diff."""
        reference = builder.build(base_dispute, base_bundle).to_array()
        for _ in range(20):
            np.testing.assert_array_equal(
                builder.build(base_dispute, base_bundle).to_array(), reference
            )

    def test_output_does_not_depend_on_the_wall_clock(
        self, make_dispute, base_bundle
    ):
        """Shifting every timestamp by a constant must not move any feature.

        This is the property that makes the corpus rebase safe, and it is the
        sharpest available test of clock-independence: if any feature were
        computed against "now" rather than against another field in the input,
        translating the input would change it.
        """
        original = make_dispute(amount="5000.00")
        shifted = original.model_copy(
            update={
                "disputed_at": original.disputed_at + timedelta(days=365),
                "respond_by": original.respond_by + timedelta(days=365),
            }
        )

        shifted_bundle = base_bundle.model_copy(
            update={
                "order": base_bundle.order.model_copy(
                    update={
                        "placed_at": base_bundle.order.placed_at
                        + timedelta(days=365)
                    }
                ),
                "session": base_bundle.session.model_copy(
                    update={
                        "login_at": base_bundle.session.login_at
                        + timedelta(days=365),
                        "account_created_at": base_bundle.session.account_created_at
                        + timedelta(days=365),
                    }
                ),
                "pod": base_bundle.pod.model_copy(
                    update={
                        "delivered_at": (
                            base_bundle.pod.delivered_at + timedelta(days=365)
                            if base_bundle.pod.delivered_at
                            else None
                        )
                    }
                ),
            }
        )

        before = builder.build(original, base_bundle)
        after = builder.build(shifted, shifted_bundle)

        np.testing.assert_allclose(
            before.to_array(), after.to_array(), rtol=0, atol=1e-9
        )

    def test_build_does_not_mutate_its_inputs(self, base_dispute, base_bundle):
        """A pure function leaves its arguments alone."""
        dispute_before = base_dispute.model_dump_json()
        bundle_before = base_bundle.model_dump_json()

        builder.build(base_dispute, base_bundle)

        assert base_dispute.model_dump_json() == dispute_before
        assert base_bundle.model_dump_json() == bundle_before


class TestFeatureContract:
    def test_vector_has_exactly_thirty_five_features(self, base_features):
        assert base_features.to_array().shape == (1, 35)
        assert len(FEATURE_ORDER) == 35

    def test_registry_order_matches_the_schema_exactly(self):
        """Column-order drift is the silent killer; assert it cannot happen."""
        assert feature_names() == FEATURE_ORDER

    def test_registry_extractors_agree_with_direct_attribute_access(
        self, base_features
    ):
        """Every registered extractor returns the field it claims to."""
        for spec in REGISTRY:
            assert spec.extract(base_features) == float(
                getattr(base_features, spec.name)
            )

    def test_array_order_matches_registry_order(self, base_features):
        array = base_features.to_array()[0]
        for index, spec in enumerate(REGISTRY):
            assert array[index] == pytest.approx(spec.extract(base_features))

    def test_feature_version_is_stamped_on_every_vector(self, base_features):
        assert base_features.feature_version == FEATURE_VERSION

    def test_every_feature_is_finite(self, base_features):
        """No NaN, no infinity. Either would silently poison a tree split."""
        assert np.all(np.isfinite(base_features.to_array()))

    def test_integer_features_hold_integral_values(self, base_features):
        for spec in REGISTRY:
            if spec.dtype != "int":
                continue
            value = spec.extract(base_features)
            assert value == int(value), (
                f"{spec.name} is declared int but holds {value}"
            )

    def test_similarity_features_stay_in_the_unit_interval(self, base_features):
        for name in (
            "recipient_name_match",
            "delivery_address_match",
            "billing_shipping_match",
            "pod_ocr_confidence",
            "evidence_completeness_score",
        ):
            value = getattr(base_features, name)
            assert 0.0 <= value <= 1.0, f"{name} out of range: {value}"

    def test_missing_delivery_timestamp_uses_the_negative_sentinel(
        self, base_dispute, make_bundle, make_pod
    ):
        """An absent timestamp must be distinguishable from a zero-hour lag."""
        bundle = make_bundle(pod=make_pod(delivered_at=None))
        features = builder.build(base_dispute, bundle)
        assert features.delivery_lag_hours == builder.NO_DELIVERY_SENTINEL
        assert features.delivered_before_dispute == 0

    def test_offshore_distance_is_zero_at_the_india_centroid(
        self, base_dispute, base_bundle
    ):
        """Sanity-check the haversine against a known point."""
        distance = builder.haversine_km(
            builder.INDIA_CENTROID_LAT,
            builder.INDIA_CENTROID_LON,
            builder.INDIA_CENTROID_LAT,
            builder.INDIA_CENTROID_LON,
        )
        assert distance == pytest.approx(0.0, abs=1e-9)

    def test_offshore_flag_trips_for_a_distant_session(
        self, base_dispute, base_bundle
    ):
        """A London IP must read as offshore; a Bengaluru one must not."""
        assert base_features_is_domestic(base_dispute, base_bundle)

        london = base_bundle.model_copy(
            update={
                "session": base_bundle.session.model_copy(
                    update={"ip_geo_lat": 51.5074, "ip_geo_lon": -0.1278}
                )
            }
        )
        features = builder.build(base_dispute, london)
        assert features.ip_is_offshore == 1
        assert features.ip_offshore_distance_km > builder.OFFSHORE_DISTANCE_KM


def base_features_is_domestic(dispute, bundle) -> bool:
    """Helper: True when the bundle's session geolocates inside India."""
    features = builder.build(dispute, bundle)
    return features.ip_is_offshore == 0
