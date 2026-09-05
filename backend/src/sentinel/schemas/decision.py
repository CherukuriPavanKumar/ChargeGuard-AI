"""Decision-side value objects -- the system's output contract.

INVARIANT 1 (decision authority): a :class:`Decision` may only be constructed
inside ``sentinel.policy.engine``.  This module *defines* the type; it does not
instantiate it, and neither does anything else.  ``tests/test_decision_authority.py``
walks the source tree with the ``ast`` module and fails the build if any other
file calls ``Decision(...)`` or one of its alternative constructors.

The reason is not stylistic.  The ML model returns a float.  The LLM returns
prose.  If either could mint a Decision, the economic guarantee -- that we
contest exactly when ``p_i * A_i >= lambda * c`` -- would no longer be provable
by reading one file.  Funnelling every decision through a single 90-line module
makes the guarantee auditable.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class DecisionAction(StrEnum):
    """The only two things ChargeGuard can do with a dispute.

    There is deliberately no ``ESCALATE`` or ``REVIEW`` value.  A third option
    would let the system defer the economic question it exists to answer.
    """

    CONTEST = "CONTEST"
    """Spend the representment cost ``c`` and fight. Chosen when expected
    recovery ``p_i * A_i`` clears the risk-adjusted cost ``lambda * c``."""

    ACCEPT = "ACCEPT"
    """Concede the chargeback. Chosen when contesting is negative-expectancy,
    or when a hard gate makes the dispute unwinnable on scheme rules."""


class GateResult(BaseModel):
    """Outcome of evaluating one hard-override policy gate.

    Every gate result is retained on the Decision, fired or not.  An auditor
    reading a Decision can therefore see not only why we did what we did, but
    which alternative rules were considered and rejected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_name: str = Field(
        ..., min_length=1, description="Stable identifier of the gate."
    )
    fired: bool = Field(
        ..., description="Whether this gate's precondition was met."
    )
    forced_action: DecisionAction | None = Field(
        default=None,
        description=(
            "Action this gate mandates when it fires. None when the gate did "
            "not fire."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Human-readable justification, citing the scheme rule or economic "
            "argument. This text is surfaced verbatim in the UI gate trace."
        ),
    )


class Decision(BaseModel):
    """The full, auditable record of one contest-or-accept determination.

    Constructed only by ``sentinel.policy.engine.decide``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dispute_id: str = Field(..., min_length=1, description="Dispute this decides.")
    action: DecisionAction = Field(..., description="CONTEST or ACCEPT.")
    win_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Calibrated P(win | evidence). A genuine probability, not a ranking "
            "score -- it is multiplied by rupees, so miscalibration would "
            "corrupt every threshold comparison."
        ),
    )
    threshold: float = Field(
        ...,
        ge=0.0,
        description=(
            "Per-dispute break-even probability lambda*c/A_i. Values above 1.0 "
            "mean the threshold is unreachable and ACCEPT is forced."
        ),
    )
    expected_value_inr: Decimal = Field(
        ...,
        description=(
            "E[contest] - E[accept] = p_i*A_i - c, in rupees. Negative values "
            "quantify the loss avoided by conceding."
        ),
    )
    gates_evaluated: list[GateResult] = Field(
        ...,
        description="Every gate considered, in evaluation order, fired or not.",
    )
    deciding_reason: str = Field(
        ...,
        min_length=1,
        description=(
            "Name of the gate that forced the action, or 'EV_RULE' when the "
            "economic comparison decided it."
        ),
    )
    feature_version: str = Field(
        ..., description="Feature contract version used to score this dispute."
    )
    model_version: str = Field(
        ..., description="Win-probability model artifact version."
    )
    latency_ms: float = Field(
        ..., ge=0.0, description="Wall-clock milliseconds spent producing this decision."
    )
    decided_at: datetime = Field(..., description="UTC timestamp of the decision.")

    @field_serializer("expected_value_inr")
    def _ser_ev(self, v: Decimal) -> float:
        """Emit rupee amounts as JSON numbers so the frontend can do arithmetic."""
        return float(v)

    @property
    def fired_gate(self) -> GateResult | None:
        """The gate that decided this, if any; None when the EV rule decided."""
        for gate in self.gates_evaluated:
            if gate.fired:
                return gate
        return None

    @property
    def margin(self) -> float:
        """Signed distance from the threshold, ``p_i - p*``.

        Positive means the economics favour contesting.  Useful for sorting a
        queue by how close a call each dispute was.
        """
        return self.win_probability - self.threshold


class PacketSource(StrEnum):
    """Which synthesiser produced the rebuttal narrative."""

    LLM = "LLM"
    """Claude produced and validated the draft."""

    TEMPLATE = "TEMPLATE"
    """Deterministic template fallback, used when the LLM was unavailable,
    returned unparseable output twice, or cited artifacts not in the bundle."""


class EvidencePacket(BaseModel):
    """The representment document assembled for a CONTEST decision.

    The packet is downstream of the decision and can never influence it.  It is
    generated only after ``action is CONTEST``, on a background job, off the
    latency-critical scoring path.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dispute_id: str = Field(..., min_length=1, description="Dispute this defends.")
    reason_code: str = Field(..., description="Scheme reason code being rebutted.")
    summary: str = Field(..., description="One-paragraph case summary for the issuer.")
    evidence_narrative: str = Field(
        ..., description="Prose walkthrough of the artifacts, in scheme order."
    )
    scheme_argument: str = Field(
        ...,
        description="Reason-code-specific argument citing the applicable rule.",
    )
    cited_artifacts: tuple[str, ...] = Field(
        default=(),
        description=(
            "Artifact identifiers referenced in the narrative. Validated "
            "against the bundle -- a citation to something absent is treated "
            "as a hallucination and rejects the whole draft."
        ),
    )
    source: PacketSource = Field(
        ..., description="Whether the LLM or the template produced this."
    )
    html: str = Field(..., description="Rendered representment document as HTML.")
    pdf_path: str | None = Field(
        default=None,
        description=(
            "Filesystem path to the rendered PDF, or None when the PDF engine "
            "is unavailable and only HTML was produced."
        ),
    )
    generated_at: datetime = Field(..., description="UTC generation timestamp.")


class AuditRecord(BaseModel):
    """Immutable join of a decision, its inputs, and its packet.

    Written for every scored dispute so that any historical decision can be
    reconstructed and re-litigated with the exact feature values that produced it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_id: str = Field(..., min_length=1, description="Audit record identifier.")
    dispute_id: str = Field(..., min_length=1, description="Dispute audited.")
    decision: Decision = Field(..., description="The decision as issued.")
    feature_snapshot: dict[str, float] = Field(
        ...,
        description="Exact feature values fed to the model, in registry order.",
    )
    evidence_digest: str = Field(
        ...,
        description=(
            "SHA-256 over the canonical JSON of the evidence bundle. Detects "
            "post-hoc tampering with the inputs."
        ),
    )
    packet_generated: bool = Field(
        default=False, description="Whether a representment packet was assembled."
    )
    created_at: datetime = Field(..., description="UTC timestamp of the audit write.")
