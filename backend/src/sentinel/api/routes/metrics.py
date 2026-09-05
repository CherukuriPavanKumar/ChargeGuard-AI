"""Metrics routes.

``GET /v1/metrics`` serves the artifact written by ``make eval``, byte for byte.
It does not recompute anything, and it does not synthesise a value for any field.

That is a deliberate constraint.  If the harness has not been run, this endpoint
returns an explicit empty state rather than plausible-looking zeros dressed as
results, and the dashboard renders "run `make eval`".  A metrics endpoint that
invents numbers is worse than one that returns nothing, because the numbers look
real.

``GET /v1/metrics/latency`` is the exception: it reports *live* percentiles
accumulated by the middleware since process start, which is a different question
from the offline benchmark and is labelled as such.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request

from sentinel.api.middleware import latency_snapshot
from sentinel.config import get_settings
from sentinel.features.registry import describe_registry
from sentinel.policy.gates import GATE_NAMES
from sentinel.schemas.features import FEATURE_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])

#: Returned when the harness has not been run. Shaped exactly like a real
#: payload so the dashboard needs no special-case parsing -- it checks
#: ``test_set_size == 0`` and renders the empty state.
EMPTY_METRICS: dict[str, Any] = {
    "generated_at": None,
    "test_set_size": 0,
    "classifier": {
        "precision": 0.0,
        "recall": 0.0,
        "f1": 0.0,
        "pr_auc": 0.0,
        "roc_auc": 0.0,
        "brier": 0.0,
        "ece": 0.0,
    },
    "reliability_curve": [],
    "economics": {
        "net_yield_inr": 0,
        "oracle_yield_inr": 0,
        "oracle_efficiency": 0.0,
        "fp_cost_inr": 0,
        "fn_cost_inr": 0,
        "fp_fn_ratio": 0.0,
    },
    "baselines": [],
    "latency_ms": {"p50": 0.0, "p95": 0.0, "p99": 0.0, "n": 0},
    "empty_state": True,
    "hint": "No evaluation artifact found. Run `make all` to generate it.",
}


@router.get(
    "",
    summary="Held-out evaluation metrics",
    response_description=(
        "The contents of eval/reports/metrics.json, or an explicit empty state."
    ),
)
def metrics() -> dict[str, Any]:
    """Serve the evaluation artifact produced by ``make eval``.

    Returns the empty state rather than a 404 when the harness has not run: the
    dashboard should render an instruction, not an error page.
    """
    path = get_settings().reports_dir / "metrics.json"

    if not path.is_file():
        logger.info("metrics artifact absent at %s; serving empty state", path)
        return EMPTY_METRICS

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("metrics artifact unreadable at %s: %s", path, exc)
        return {
            **EMPTY_METRICS,
            "hint": f"Evaluation artifact at {path} could not be read: {exc}",
        }

    payload["empty_state"] = int(payload.get("test_set_size", 0)) == 0
    return payload


@router.get(
    "/latency",
    summary="Live latency percentiles since process start",
    response_description="Decision-path and request-path percentiles with an SLA verdict.",
)
def latency() -> dict[str, Any]:
    """Return live p50/p95/p99 accumulated by the middleware.

    Distinct from the ``latency_ms`` block in ``/v1/metrics``, which is the
    offline benchmark over 1 000 calls from the evaluation harness. This one
    reflects whatever traffic this process has actually served, and reports zero
    observations honestly when it has served none.
    """
    return latency_snapshot(get_settings().latency_sla_ms)


@router.get(
    "/features",
    summary="The feature registry",
    response_description="Ordered feature contract with families, dtypes and descriptions.",
)
def features() -> dict[str, Any]:
    """Publish the feature contract.

    Exposed because a decision carrying ``feature_version: v1`` is only
    auditable if v1's meaning is retrievable. This is that record.
    """
    return {
        "feature_version": FEATURE_VERSION,
        "n_features": len(describe_registry()),
        "features": describe_registry(),
    }


@router.get(
    "/policy",
    summary="The live economic policy",
    response_description="Representment cost, risk margin, gate order and worked thresholds.",
)
def policy(request: Request) -> dict[str, Any]:
    """Publish the economic policy currently in force.

    Includes worked threshold examples at several amounts, because
    ``lambda * c / A`` is the one formula a reader needs to check by hand to
    verify the system does what it claims.
    """
    settings = get_settings()
    from sentinel.policy import economics

    cost = settings.representment_cost_inr
    margin = settings.risk_margin

    worked = []
    for amount in ("450", "1200", "2400", "8900", "32000", "80000"):
        from decimal import Decimal

        value = Decimal(amount)
        raw = economics.decision_threshold(value, cost, margin)
        worked.append(
            {
                "amount_inr": float(value),
                "threshold": round(raw, 6),
                "reachable": economics.is_threshold_reachable(raw),
                "fn_fp_ratio": round(
                    economics.cost_asymmetry_ratio(value, cost), 4
                ),
            }
        )

    model = getattr(request.app.state, "model", None)
    return {
        "representment_cost_inr": float(cost),
        "risk_margin": margin,
        "formula": "contest  <=>  p_win >= (risk_margin * cost) / amount",
        "breakeven_amount_inr": float(economics.breakeven_amount(cost, margin)),
        "gate_order": list(GATE_NAMES),
        "worked_thresholds": worked,
        "feature_version": FEATURE_VERSION,
        "model_version": model.model_version if model is not None else None,
    }
