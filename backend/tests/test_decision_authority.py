"""INVARIANT 1: only ``policy/engine.py`` may construct a ``Decision``.

This test is the enforcement mechanism for the architectural claim the whole
submission rests on: *the ML model returns a float, the LLM returns prose, and
neither decides anything*.

That claim is only worth making if it is checkable.  A convention maintained by
discipline degrades the first time someone is in a hurry.  So this walks every
``.py`` file under ``backend/`` with the :mod:`ast` module and fails the build if
``Decision`` is instantiated anywhere it should not be.

Why AST rather than grep
------------------------
``grep 'Decision('`` produces false positives on the class definition, on type
annotations, on docstrings mentioning the word, and on ``EvidencePacket(`` if the
pattern is loosened. It produces false *negatives* on ``Decision.model_validate``
and on aliased imports. Parsing the syntax tree distinguishes a call from a
mention, which is the actual property under test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: ``backend/`` -- the root of everything scanned.
BACKEND_ROOT = Path(__file__).resolve().parents[1]

#: The class whose construction is restricted.
GUARDED_CLASS = "Decision"

#: Alternative constructors on a Pydantic model. Calling any of these builds an
#: instance just as surely as calling the class, so all are guarded.
ALTERNATIVE_CONSTRUCTORS = frozenset(
    {"model_validate", "model_validate_json", "model_construct", "construct"}
)

#: Files permitted to construct a Decision, relative to ``backend/``.
#:
#: ``schemas/decision.py`` defines the class. ``policy/engine.py`` is the sole
#: decision authority. Nothing else, including the tests, appears here -- the
#: test suite builds Decisions by calling the engine, exactly as production does.
ALLOWED = frozenset(
    {
        Path("src/sentinel/schemas/decision.py"),
        Path("src/sentinel/policy/engine.py"),
    }
)

#: Directories excluded from the walk: build output and virtual environments.
EXCLUDED_DIRS = frozenset(
    {".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist", ".git"}
)


def _python_files() -> list[Path]:
    """Every ``.py`` file under ``backend/``, excluding build and venv output."""
    files: list[Path] = []
    for path in BACKEND_ROOT.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _constructs_guarded_class(node: ast.Call) -> bool:
    """True when this call node instantiates the guarded class.

    Two forms are recognised:

    * ``Decision(...)``                  -- ``func`` is a Name
    * ``Decision.model_validate(...)``   -- ``func`` is an Attribute on a Name
    """
    func = node.func

    if isinstance(func, ast.Name) and func.id == GUARDED_CLASS:
        return True

    if isinstance(func, ast.Attribute) and func.attr in ALTERNATIVE_CONSTRUCTORS:
        value = func.value
        if isinstance(value, ast.Name) and value.id == GUARDED_CLASS:
            return True

    return False


def _find_violations(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, source_segment)`` for every guarded construction."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:  # pragma: no cover - a parse failure fails elsewhere
        pytest.fail(f"{path} does not parse: {exc}")

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _constructs_guarded_class(node):
            segment = ast.get_source_segment(source, node) or GUARDED_CLASS
            violations.append((node.lineno, segment.splitlines()[0][:90]))
    return violations


class TestDecisionAuthority:
    def test_source_tree_is_non_empty(self):
        """Guard against the walk silently matching nothing.

        A test that scans zero files passes trivially and proves nothing. This
        asserts the scan actually found the codebase.
        """
        files = _python_files()
        assert len(files) > 25, (
            f"expected to scan the whole backend, found only {len(files)} files"
        )

    def test_only_the_engine_constructs_decisions(self):
        """**INVARIANT 1.** Walk every file; fail on any unauthorised construction."""
        offenders: dict[str, list[tuple[int, str]]] = {}

        for path in _python_files():
            relative = path.relative_to(BACKEND_ROOT)
            if relative in ALLOWED:
                continue
            violations = _find_violations(path)
            if violations:
                offenders[str(relative)] = violations

        if offenders:
            lines = [
                "Decision may only be constructed in sentinel/policy/engine.py.",
                "",
                "Unauthorised constructions found:",
            ]
            for filename, violations in sorted(offenders.items()):
                for lineno, segment in violations:
                    lines.append(f"  {filename}:{lineno}  {segment}")
            lines += [
                "",
                "The ML model returns a float and the LLM returns prose. Neither",
                "decides anything. Route this through sentinel.policy.engine.decide.",
            ]
            pytest.fail("\n".join(lines))

    def test_the_engine_does_construct_decisions(self):
        """The converse: the authority must actually exercise its authority.

        Without this, the invariant could be satisfied by a codebase that never
        constructs a Decision at all, which would pass the test above while
        being entirely broken.
        """
        engine_path = BACKEND_ROOT / "src" / "sentinel" / "policy" / "engine.py"
        violations = _find_violations(engine_path)
        assert violations, (
            "policy/engine.py must construct Decision -- it is the sole "
            "decision authority and evidently is not deciding anything"
        )

    def test_model_layer_does_not_import_the_decision_type(self):
        """The model layer must not even be able to name a Decision.

        Stronger than the construction check and cheap to enforce: a module that
        cannot import the type cannot be one refactor away from building one.
        """
        model_files = [
            BACKEND_ROOT / "src" / "sentinel" / "models" / "win_probability.py",
            BACKEND_ROOT / "src" / "sentinel" / "models" / "calibration.py",
        ]

        for path in model_files:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imported = {alias.name for alias in node.names}
                    assert GUARDED_CLASS not in imported, (
                        f"{path.name} imports {GUARDED_CLASS}; the model layer "
                        f"returns a float and must not know decisions exist"
                    )

    def test_llm_layer_does_not_import_the_decision_type(self):
        """The synthesiser must not be able to see the decision it writes for.

        ``PacketSource`` is imported from the same module and that is fine -- it
        describes provenance of the prose, not the action taken.
        """
        llm_dir = BACKEND_ROOT / "src" / "sentinel" / "llm"

        for path in llm_dir.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    imported = {alias.name for alias in node.names}
                    assert GUARDED_CLASS not in imported, (
                        f"{path.name} imports {GUARDED_CLASS}; the LLM writes "
                        f"prose downstream of the decision and must not see it"
                    )

    def test_synthesiser_signature_excludes_decision_state(self):
        """``synthesise`` must not accept p_win, threshold, or a decision.

        Enforced on the signature rather than by convention, so a future caller
        cannot pass them accidentally and no reviewer has to notice.
        """
        path = BACKEND_ROOT / "src" / "sentinel" / "llm" / "synthesiser.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        forbidden = {"p_win", "threshold", "decision", "action", "win_probability"}
        checked = False

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "synthesise":
                checked = True
                names = {arg.arg for arg in node.args.args}
                names |= {arg.arg for arg in node.args.kwonlyargs}
                leaked = names & forbidden
                assert not leaked, (
                    f"synthesise() accepts decision state {sorted(leaked)}; the "
                    f"LLM must never receive p_win, the threshold, or the action"
                )

        assert checked, "synthesise() not found in llm/synthesiser.py"

    def test_packet_builder_signature_excludes_decision_state(self):
        """``build_packet`` likewise cannot see the decision it documents."""
        path = BACKEND_ROOT / "src" / "sentinel" / "packet" / "renderer.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        forbidden = {"p_win", "threshold", "decision", "win_probability"}
        checked = False

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "build_packet":
                checked = True
                names = {arg.arg for arg in node.args.args}
                names |= {arg.arg for arg in node.args.kwonlyargs}
                leaked = names & forbidden
                assert not leaked, (
                    f"build_packet() accepts decision state {sorted(leaked)}"
                )

        assert checked, "build_packet() not found in packet/renderer.py"

    def test_baselines_return_arrays_not_decisions(self):
        """Evaluation baselines are policies over arrays, not pipeline participants.

        If a baseline could mint a Decision it would be indistinguishable from
        the real policy in the audit trail.
        """
        path = BACKEND_ROOT / "eval" / "baselines.py"
        assert not _find_violations(path), (
            "eval/baselines.py must not construct Decisions; baselines are "
            "array-valued policies scored by eval.economics"
        )
