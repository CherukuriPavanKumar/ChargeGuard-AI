"""The decision authority.

INVARIANT 1: **this module is the only place in the codebase permitted to
construct a** :class:`~sentinel.schemas.decision.Decision`.

``tests/test_decision_authority.py`` parses every ``.py`` file under
``backend/`` with the ``ast`` module and fails if ``Decision(...)``,
``Decision.model_validate(...)``, or ``Decision.model_construct(...)`` appears
anywhere except here and in the module that defines the class.

Why this matters
----------------
The system has two components that are *not* trustworthy in the formal sense:

* the gradient-boosted model, which returns a float it cannot justify;
* the language model, which returns fluent prose that may be confabulated.

Neither is allowed to decide anything.  The model's float enters this module as
``p_win`` and is compared against an arithmetic threshold.  The LLM's prose is
generated *after* the decision, from a packet builder that never sees the
action, and cannot feed back.  Everything that determines whether the company
spends money passes through :func:`decide`, which is short enough to read in one
sitting and has no branches that are not visible in its gate trace.

Decision flow
-------------
1. Evaluate all six gates (no short-circuit -- the full trace is retained).
2. If any gate fired, take the first one's forced action.  Done.
3. Otherwise compute ``p* = lambda * c / A_i``.
4. If ``p*`` exceeds 1.0 the threshold is unreachable: ACCEPT.
5. Otherwise CONTEST iff ``p_win >= p*``.

The expected value is computed and recorded in every branch, including gated
ones, so the audit trail always answers "what would this have been worth?"
"""

from __future__ import annotations

from decimal import Decimal
from time import perf_counter

from sentinel.config import Settings, get_settings
from sentinel.policy import economics, gates
from sentinel.schemas.decision import Decision, DecisionAction, GateResult
from sentinel.schemas.dispute import DisputeEvent
from sentinel.schemas.evidence import EvidenceBundle
from sentinel.schemas.features import FeatureVector

#: Recorded as ``deciding_reason`` when no gate fired and economics decided.
EV_RULE: str = "EV_RULE"


def decide(
    dispute: DisputeEvent,
    bundle: EvidenceBundle,
    features: FeatureVector,
    p_win: float,
    model_version: str,
    settings: Settings | None = None,
    started_at: float | None = None,
) -> Decision:
    """Determine whether to contest ``dispute``, and record why.

    Args:
        dispute: The inbound chargeback.
        bundle: All evidence held for it.
        features: The pure feature vector built from the two above.
        p_win: Calibrated ``P(win)`` from the model. A float, nothing more --
            this function decides what it means.
        model_version: Artifact version of the model that produced ``p_win``.
        settings: Configuration; the process singleton when omitted.
        started_at: A ``perf_counter()`` reading from the top of the request, so
            reported latency covers feature building and inference rather than
            just this function. Defaults to now.

    Returns:
        A fully populated :class:`Decision` carrying the complete gate trace.

    Raises:
        ValueError: if ``p_win`` is outside [0, 1]. A model that emits a
            probability outside the unit interval is broken, and silently
            clamping would hide that from the audit trail.
    """
    if not 0.0 <= p_win <= 1.0:
        raise ValueError(
            f"p_win must be a probability in [0, 1], got {p_win!r}. "
            f"An uncalibrated or malfunctioning model must fail loudly here."
        )

    cfg = settings if settings is not None else get_settings()
    t0 = started_at if started_at is not None else perf_counter()

    cost = cfg.representment_cost_inr
    amount = dispute.amount_inr

    # -- 1. economics, computed unconditionally so gated decisions are still
    #       accompanied by "what would this have been worth?" ----------------
    threshold = economics.decision_threshold(amount, cost, cfg.risk_margin)
    ev = economics.expected_value(p_win, amount, cost)

    # -- 2. gates, evaluated in full -------------------------------------- #
    gate_results: list[GateResult] = gates.evaluate_all(
        dispute, bundle, features, cfg
    )
    fired = gates.first_fired(gate_results)

    if fired is not None and fired.forced_action is not None:
        action = fired.forced_action
        deciding_reason = fired.gate_name
    else:
        action, deciding_reason = _apply_ev_rule(p_win, threshold)

    latency_ms = (perf_counter() - t0) * 1000.0

    return Decision(
        dispute_id=dispute.dispute_id,
        action=action,
        win_probability=p_win,
        threshold=threshold,
        expected_value_inr=ev,
        gates_evaluated=gate_results,
        deciding_reason=deciding_reason,
        feature_version=features.feature_version,
        model_version=model_version,
        latency_ms=latency_ms,
        decided_at=gates.utc_now(),
    )


def _apply_ev_rule(p_win: float, threshold: float) -> tuple[DecisionAction, str]:
    """Apply the expected-value comparison when no gate has fired.

    Returns the action and the ``deciding_reason`` string.  Split out from
    :func:`decide` so the arithmetic can be read and tested in isolation from
    the object construction.
    """
    if not economics.is_threshold_reachable(threshold):
        # lambda*c/A > 1: no probability clears the bar. Distinguished from a
        # low score so the audit trail says "arithmetic", not "low confidence".
        return DecisionAction.ACCEPT, EV_RULE

    if p_win >= threshold:
        return DecisionAction.CONTEST, EV_RULE
    return DecisionAction.ACCEPT, EV_RULE


def explain(decision: Decision, settings: Settings | None = None) -> str:
    """Render a one-paragraph plain-English explanation of a decision.

    Used by the simulate route and the CLI report.  Reads only the Decision, so
    it can explain a decision reconstructed from an audit record months later.
    """
    cfg = settings if settings is not None else get_settings()
    cost = cfg.representment_cost_inr

    fired = decision.fired_gate
    if fired is not None:
        head = (
            f"{decision.action}: policy gate '{fired.gate_name}' fired. "
            f"{fired.rationale}"
        )
    elif not economics.is_threshold_reachable(decision.threshold):
        head = (
            f"{decision.action}: the break-even probability is "
            f"{decision.threshold:.3f}, which exceeds certainty. No evidence "
            f"could make this dispute profitable to contest."
        )
    else:
        comparator = ">=" if decision.action is DecisionAction.CONTEST else "<"
        head = (
            f"{decision.action}: calibrated win probability "
            f"{decision.win_probability:.3f} {comparator} break-even threshold "
            f"{decision.threshold:.3f}."
        )

    tail = (
        f" Expected value of contesting is INR {decision.expected_value_inr:,.2f} "
        f"at a representment cost of INR {cost:,.2f}. "
        f"Decided in {decision.latency_ms:.1f} ms using features "
        f"{decision.feature_version} and model {decision.model_version}."
    )
    return head + tail


def would_contest(
    amount_inr: Decimal, p_win: float, settings: Settings | None = None
) -> bool:
    """Pure economics shortcut: ignore gates, apply only the EV rule.

    Exists for the evaluation harness's baseline comparisons and for the
    threshold-sensitivity sweep, where gate semantics are held constant and only
    the arithmetic varies.  **Not** a decision path -- it returns a bool, never a
    :class:`Decision`.
    """
    cfg = settings if settings is not None else get_settings()
    threshold = economics.decision_threshold(
        amount_inr, cfg.representment_cost_inr, cfg.risk_margin
    )
    if not economics.is_threshold_reachable(threshold):
        return False
    return p_win >= threshold
