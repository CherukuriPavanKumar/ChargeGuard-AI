"""FastAPI application.

Start with ``make serve`` (``uvicorn sentinel.api.main:app``).

Startup behaviour
=================
The win-probability model is loaded **once**, at startup, into application
state.  Loading per request would put two file reads inside a 200 ms budget, and
would make the p95 a function of page cache behaviour rather than of the code.

If the artifacts are missing, the application still starts.  That is deliberate:
``/health`` must be reachable to *report* that the model is missing, and
``/v1/metrics`` must be reachable to serve its empty state.  A process that
refuses to boot cannot tell anyone why.  Scoring routes then return 503 with the
command needed to fix it.

Capability reporting
====================
``/health`` reports the real state of four optional dependencies -- the model
artifacts, the OCR engine, the LLM, and the PDF renderer.  Three of those are
commonly absent on a clean machine, and the system is designed to work without
them. Reporting ``"status": "ok"`` while silently templating every packet would
misrepresent what the deployment is actually doing.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sentinel import __version__
from sentinel.api.middleware import RequestContextMiddleware
from sentinel.api.routes import disputes, metrics, simulate
from sentinel.config import get_settings
from sentinel.extraction import ocr
from sentinel.llm import synthesiser
from sentinel.models.win_probability import ModelArtifactsMissing, WinProbabilityModel
from sentinel.packet import renderer
from sentinel.schemas.features import FEATURE_VERSION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("sentinel.api")

DESCRIPTION = """
**ChargeGuard.AI** decides which merchant chargeback disputes are economically worth
contesting, assembles scheme-compliant rebuttal evidence, and proves its own
value with held-out metrics.

### The one rule

    contest  <=>  p_win >= (lambda * c) / amount

The threshold is **per dispute**, not global. A INR 450 dispute needs
near-certainty; a INR 40,000 dispute is worth contesting at low confidence.

### Trust boundaries

The gradient-boosted model returns a float. The language model returns prose.
**Neither decides anything.** Every decision is constructed in
`sentinel.policy.engine`, which is the only module in the codebase permitted to
build a `Decision`, and that restriction is enforced by an AST-walking test.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the model once at startup; degrade visibly if it is absent."""
    settings = get_settings()
    app.state.model = None
    app.state.model_error = None

    try:
        app.state.model = WinProbabilityModel.load(settings)
        logger.info(
            "model loaded: %s (features %s)",
            app.state.model.model_version,
            FEATURE_VERSION,
        )
    except (ModelArtifactsMissing, Exception) as exc:  # noqa: B014
        # The API must boot so /health can report this. Scoring routes 503.
        app.state.model_error = f"{type(exc).__name__}: {exc}"
        logger.error("model unavailable: %s", app.state.model_error)

    logger.info(
        "capabilities: ocr=%s llm=%s pdf=%s",
        ocr.engine_available(),
        synthesiser.llm_available(settings),
        renderer.pdf_engine_available(),
    )

    yield

    app.state.model = None


app = FastAPI(
    title="ChargeGuard.AI",
    version=__version__,
    description=DESCRIPTION,
    lifespan=lifespan,
    contact={"name": "ChargeGuard.AI", "url": "https://github.com/"},
    license_info={"name": "MIT"},
)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
)

app.include_router(disputes.router)
app.include_router(simulate.router)
app.include_router(metrics.router)


@app.get("/health", tags=["ops"], summary="Liveness and capability report")
def health() -> dict[str, Any]:
    """Report liveness and the true state of every optional dependency.

    ``status`` is ``ok`` only when the model is loaded, because without it the
    service cannot do the one thing it exists to do. The three optional
    capabilities are reported separately and their absence is ``degraded``, not
    ``error`` -- the system has working fallbacks for all three and says so.
    """
    settings = get_settings()
    model = getattr(app.state, "model", None)

    capabilities = {
        "model": {
            "available": model is not None,
            "version": model.model_version if model is not None else None,
            "error": getattr(app.state, "model_error", None),
            "fallback": None if model is not None else "none - scoring returns 503",
        },
        "ocr": {
            "available": ocr.engine_available(),
            "fallback": "POD parses as UNVERIFIED; policy reasons with less evidence",
        },
        "llm": {
            "available": synthesiser.llm_available(settings),
            "model": settings.llm_model,
            "fallback": "deterministic reason-code templates in sentinel.llm.templates",
        },
        "pdf": {
            "available": renderer.pdf_engine_available(),
            "fallback": "HTML packet is produced; pdf_path is null",
        },
    }

    degraded = [
        name
        for name, cap in capabilities.items()
        if name != "model" and not cap["available"]
    ]

    return {
        "status": "ok" if model is not None else "degraded",
        "version": __version__,
        "feature_version": FEATURE_VERSION,
        "economics": {
            "representment_cost_inr": float(settings.representment_cost_inr),
            "risk_margin": settings.risk_margin,
        },
        "capabilities": capabilities,
        "degraded_capabilities": degraded,
        "note": (
            "Degraded optional capabilities are expected on a clean machine and "
            "are handled by implemented fallbacks, not by failing requests."
        ),
    }


@app.get("/", tags=["ops"], summary="Service banner")
def root() -> dict[str, Any]:
    """Return a terse banner pointing at the interactive documentation."""
    return {
        "service": "ChargeGuard.AI",
        "tagline": "Autonomous Multi-Modal Chargeback Defense & Economic Arbitrage Engine",
        "version": __version__,
        "rule": "contest <=> p_win >= (lambda * c) / amount",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "endpoints": [
            "POST /v1/disputes/score",
            "POST /v1/disputes/{id}/packet",
            "GET  /v1/disputes/jobs/{job_id}",
            "GET  /v1/simulate",
            "GET  /v1/simulate/{preset}",
            "GET  /v1/metrics",
            "GET  /v1/metrics/latency",
            "GET  /v1/metrics/features",
            "GET  /v1/metrics/policy",
            "GET  /health",
        ],
    }
