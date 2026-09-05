"""Central configuration.

Two of these values -- ``representment_cost_inr`` (``c``) and ``risk_margin``
(``lambda``) -- are the entire economic policy of the system.  Everything else
is plumbing.  They live here, in one place, typed and documented, rather than
being scattered as literals through the policy code.

Calibration of the defaults
---------------------------
``c = 350`` INR is the all-in cost of assembling and filing one representment:
scheme representment fee, acquirer handling, and amortised analyst time.

``lambda = 1.2`` adds a 20% margin over pure break-even.  It buys robustness
against model miscalibration: if the calibrated probability is optimistic by a
few points, a lambda of 1.0 would tip marginal cases into negative expectancy.

These two numbers produce exactly the behaviour the design calls for::

    A =    450  ->  p* = 1.2 * 350 /   450 = 0.933   (near-certainty required)
    A =  2 400  ->  p* = 1.2 * 350 /  2400 = 0.175
    A = 40 000  ->  p* = 1.2 * 350 / 40000 = 0.011   (worth a long shot)

Override any field via environment variables prefixed ``ChargeGuard_``, e.g.
``ChargeGuard_REPRESENTMENT_COST_INR=500``.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Repository-relative anchor: ``backend/`` directory.
BACKEND_ROOT: Path = Path(__file__).resolve().parents[2]

#: Repository root, one level above ``backend/``.
REPO_ROOT: Path = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Runtime configuration, environment-overridable."""

    model_config = SettingsConfigDict(
        env_prefix="ChargeGuard_",
        env_file=".env",
        extra="ignore",
    )

    # ---------------------------------------------------------------- #
    # Economics -- the policy surface                                  #
    # ---------------------------------------------------------------- #
    representment_cost_inr: Decimal = Field(
        default=Decimal("350"),
        gt=0,
        description="Fully-loaded cost 'c' of filing one representment, in INR.",
    )
    risk_margin: float = Field(
        default=1.2,
        ge=1.0,
        description=(
            "Risk margin 'lambda'. 1.0 is pure break-even; higher values demand "
            "more expected recovery before committing the representment spend."
        ),
    )

    # ---------------------------------------------------------------- #
    # Extraction thresholds                                            #
    # ---------------------------------------------------------------- #
    ocr_confidence_floor: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description=(
            "Mean OCR confidence below which a parse is downgraded to "
            "LOW_CONFIDENCE rather than VERIFIED."
        ),
    )
    strong_name_match_floor: float = Field(
        default=0.9,
        ge=0.0,
        le=1.0,
        description=(
            "Recipient-name similarity above which, with a VERIFIED signed POD, "
            "``strong_evidence_gate`` forces CONTEST irrespective of the model."
        ),
    )

    # ---------------------------------------------------------------- #
    # Data generation                                                  #
    # ---------------------------------------------------------------- #
    n_disputes_total: int = Field(
        default=20_000, gt=0, description="Total synthetic disputes to generate."
    )
    n_disputes_train: int = Field(
        default=15_000, gt=0, description="Rows in the training split."
    )
    n_disputes_test: int = Field(
        default=5_000, gt=0, description="Rows in the held-out test split."
    )
    n_pod_images: int = Field(
        default=40,
        ge=0,
        description=(
            "Proof-of-delivery images rendered to disk. The full 20k corpus uses "
            "a numeric OCR-degradation model; these images exercise the real "
            "pytesseract path in the demo and in tests."
        ),
    )

    # ---------------------------------------------------------------- #
    # LLM                                                              #
    # ---------------------------------------------------------------- #
    anthropic_api_key: str = Field(
        default="",
        description="Anthropic API key. Empty means template fallback, always.",
    )
    llm_model: str = Field(
        default="claude-sonnet-5",
        description="Model id used for rebuttal synthesis.",
    )
    llm_timeout_s: float = Field(
        default=20.0, gt=0, description="Per-request LLM timeout in seconds."
    )
    llm_max_tokens: int = Field(
        default=1500, gt=0, description="Output token ceiling for rebuttal drafts."
    )

    # ---------------------------------------------------------------- #
    # Serving                                                          #
    # ---------------------------------------------------------------- #
    cors_origins: tuple[str, ...] = Field(
        default=("http://localhost:5173", "http://127.0.0.1:5173"),
        description="Origins permitted to call the API from a browser.",
    )
    latency_sla_ms: float = Field(
        default=200.0,
        gt=0,
        description="p95 budget for the synchronous scoring path, in milliseconds.",
    )

    # ---------------------------------------------------------------- #
    # Paths                                                            #
    # ---------------------------------------------------------------- #
    @property
    def data_dir(self) -> Path:
        """Generated datasets. Git-ignored; rebuilt by ``make data``."""
        return BACKEND_ROOT / "data"

    @property
    def pod_dir(self) -> Path:
        """Rendered proof-of-delivery images."""
        return self.data_dir / "pods"

    @property
    def artifacts_dir(self) -> Path:
        """Pickled model and calibrator artifacts."""
        return BACKEND_ROOT / "src" / "sentinel" / "models" / "artifacts"

    @property
    def reports_dir(self) -> Path:
        """Evaluation outputs: ``metrics.json`` and ``REPORT.md``."""
        return BACKEND_ROOT / "eval" / "reports"

    @property
    def packets_dir(self) -> Path:
        """Rendered representment packets."""
        return self.data_dir / "packets"

    @property
    def frontend_data_dir(self) -> Path:
        """Where ``make eval`` copies ``metrics.json`` for the dashboard."""
        return REPO_ROOT / "frontend" / "src" / "data"

    def ensure_dirs(self) -> None:
        """Create every writable directory. Idempotent."""
        for path in (
            self.data_dir,
            self.pod_dir,
            self.artifacts_dir,
            self.reports_dir,
            self.packets_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()


#: Convenience handle. Prefer ``get_settings()`` in code that may be reconfigured
#: under test; this module-level alias exists for read-only call sites.
settings = get_settings()
