"""Dispute scoring and packet generation routes.

Two endpoints with deliberately different shapes, because they have deliberately
different cost profiles:

``POST /v1/disputes/score``
    **Synchronous.** Pure feature construction, in-process tree traversal,
    isotonic lookup, six gate evaluations, Decision construction. No LLM, no OCR
    on demand, no network egress of any kind. This is the path the 200 ms p95
    budget governs, and it clears it by three orders of magnitude.

``POST /v1/disputes/{id}/packet``
    **Asynchronous.** Calls a language model and a native PDF engine, neither of
    which belongs inside a latency budget. Returns a job id immediately and
    renders in the background.

Splitting them is the point.  A merchant's dispute queue needs scoring decisions
in real time to triage; it does not need the representment PDF in real time,
because a human reviews it before filing anyway.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from sentinel.api.middleware import record_decision_latency
from sentinel.config import get_settings
from sentinel.features import builder
from sentinel.ingest.evidence_loader import EvidenceParseError, assemble
from sentinel.ingest.webhook import WebhookParseError, parse_dispute_webhook
from sentinel.models.win_probability import ModelArtifactsMissing
from sentinel.packet import renderer
from sentinel.policy import engine
from sentinel.schemas.decision import Decision, DecisionAction, EvidencePacket
from sentinel.schemas.dispute import DisputeEvent
from sentinel.schemas.evidence import EvidenceBundle

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/disputes", tags=["disputes"])


# --------------------------------------------------------------------------- #
# Request / response models                                                   #
# --------------------------------------------------------------------------- #


class ScoreRequest(BaseModel):
    """Everything needed to score one dispute.

    ``dispute`` accepts either a full acquirer webhook envelope or a bare
    dispute entity; :func:`sentinel.ingest.webhook.parse_dispute_webhook`
    normalises both.
    """

    model_config = ConfigDict(extra="forbid")

    dispute: dict[str, Any] = Field(
        ...,
        description="Acquirer dispute webhook envelope, or a bare dispute entity.",
    )
    order: dict[str, Any] = Field(
        ..., description="Merchant order record from the OMS."
    )
    session: dict[str, Any] = Field(
        ..., description="Checkout session telemetry."
    )
    pod: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Pre-structured proof-of-delivery record. Ignored when "
            "``pod_image_path`` is supplied."
        ),
    )
    pod_image_path: str | None = Field(
        default=None,
        description=(
            "Path to a courier slip image. When present, real OCR runs against "
            "it. An OCR failure degrades the bundle rather than failing the "
            "request."
        ),
    )
    prior_dispute_count: int = Field(
        default=0, ge=0, description="Prior disputes by this cardholder."
    )
    refund_requested: bool = Field(
        default=False, description="Refund requested or issued pre-chargeback."
    )
    merchant_comms_count: int = Field(
        default=0, ge=0, description="Logged merchant-to-customer contacts."
    )


class PacketJobAccepted(BaseModel):
    """Acknowledgement returned when a packet job is queued."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., description="Poll this at /v1/disputes/jobs/{job_id}.")
    dispute_id: str = Field(..., description="Dispute the packet is being built for.")
    status: Literal["queued", "running", "done", "failed"] = Field(
        ..., description="Job state at the moment of acknowledgement."
    )
    poll_url: str = Field(..., description="Absolute path to poll for completion.")


class PacketJobState(BaseModel):
    """Current state of a packet-generation job."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., description="Job identifier.")
    dispute_id: str = Field(..., description="Dispute this job serves.")
    status: Literal["queued", "running", "done", "failed"] = Field(
        ..., description="Job state."
    )
    created_at: datetime = Field(..., description="When the job was queued.")
    completed_at: datetime | None = Field(
        default=None, description="When the job finished, if it has."
    )
    packet: EvidencePacket | None = Field(
        default=None, description="The rendered packet, present when done."
    )
    error: str | None = Field(
        default=None, description="Failure detail, present when failed."
    )


# --------------------------------------------------------------------------- #
# In-process job store                                                        #
# --------------------------------------------------------------------------- #


@dataclass
class _Job:
    """One packet-generation job.

    In-process and non-durable, which is correct for a demonstration service and
    would be wrong for production -- a restart loses queued work. A real
    deployment would put this in Redis or a task queue. Stated rather than
    silently implied.
    """

    job_id: str
    dispute_id: str
    status: str = "queued"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None
    packet: EvidencePacket | None = None
    error: str | None = None


class _JobStore:
    """Thread-safe bounded job registry."""

    def __init__(self, capacity: int = 512) -> None:
        self._jobs: dict[str, _Job] = {}
        self._order: list[str] = []
        self._capacity = capacity
        self._lock = Lock()

    def create(self, dispute_id: str) -> _Job:
        """Register a new queued job, evicting the oldest if at capacity."""
        job = _Job(job_id=uuid.uuid4().hex[:16], dispute_id=dispute_id)
        with self._lock:
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            while len(self._order) > self._capacity:
                self._jobs.pop(self._order.pop(0), None)
        return job

    def get(self, job_id: str) -> _Job | None:
        """Return a job by id, or None."""
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: Any) -> None:
        """Mutate a job's fields under the lock."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in changes.items():
                setattr(job, key, value)


job_store = _JobStore()


# --------------------------------------------------------------------------- #
# Shared scoring helper                                                       #
# --------------------------------------------------------------------------- #


def score_dispute(
    dispute: DisputeEvent, bundle: EvidenceBundle, request: Request
) -> Decision:
    """Run the full decision path for one dispute.

    Shared by the score route and the simulate route so both exercise identical
    code.  The model is read from application state, where it was loaded once at
    startup; loading per request would put a disk read inside the SLA.

    Raises:
        HTTPException: 503 when model artifacts are unavailable.
    """
    model = getattr(request.app.state, "model", None)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "win-probability model is not loaded. Run `make data && make "
                "train`, then restart the API."
            ),
        )

    started = perf_counter()
    features = builder.build(dispute, bundle)
    p_win = model.predict_proba(features)

    decision = engine.decide(
        dispute=dispute,
        bundle=bundle,
        features=features,
        p_win=p_win,
        model_version=model.model_version,
        settings=get_settings(),
        started_at=started,
    )
    record_decision_latency(decision.latency_ms)
    return decision


def build_inputs(payload: ScoreRequest) -> tuple[DisputeEvent, EvidenceBundle]:
    """Parse a scoring request into a dispute and an evidence bundle.

    Raises:
        HTTPException: 422 on a malformed dispute envelope, order, or session.
            Note that an *evidence gap* -- a missing or unreadable POD -- is not
            an error and never reaches here; it produces a valid degraded bundle.
    """
    try:
        dispute = parse_dispute_webhook(payload.dispute)
    except WebhookParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"dispute envelope could not be parsed: {exc}",
        ) from exc

    try:
        bundle = assemble(
            order_payload=payload.order,
            session_payload=payload.session,
            pod_image_path=payload.pod_image_path,
            pod_record=payload.pod,
            prior_dispute_count=payload.prior_dispute_count,
            refund_requested=payload.refund_requested,
            merchant_comms_count=payload.merchant_comms_count,
            settings=get_settings(),
        )
    except EvidenceParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"evidence bundle could not be assembled: {exc}",
        ) from exc

    return dispute, bundle


# --------------------------------------------------------------------------- #
# Routes                                                                      #
# --------------------------------------------------------------------------- #


@router.post(
    "/score",
    response_model=Decision,
    summary="Score one dispute and return the full decision trace",
    response_description=(
        "The decision, its per-dispute threshold, expected value, and the "
        "complete ordered gate trace."
    ),
)
def score(payload: ScoreRequest, request: Request) -> Decision:
    """Decide whether to contest one dispute.

    Synchronous and latency-budgeted. Returns the real
    :class:`~sentinel.schemas.decision.Decision` -- the same object the
    evaluation harness scores and the same one written to the audit log. There
    is no separate API-facing decision shape that could drift from it.
    """
    dispute, bundle = build_inputs(payload)
    return score_dispute(dispute, bundle, request)


def _render_packet_job(job_id: str, dispute: DisputeEvent, bundle: EvidenceBundle) -> None:
    """Background worker: synthesise and render, recording the outcome.

    Catches everything. A background task that raises would leave the job stuck
    in ``running`` forever with no way for a client to learn what happened.
    """
    job_store.update(job_id, status="running")
    try:
        packet = renderer.build_packet(dispute, bundle, get_settings())
    except Exception as exc:
        logger.exception("packet job %s failed", job_id)
        job_store.update(
            job_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            completed_at=datetime.now(timezone.utc),
        )
        return

    job_store.update(
        job_id,
        status="done",
        packet=packet,
        completed_at=datetime.now(timezone.utc),
    )


@router.post(
    "/{dispute_id}/packet",
    response_model=PacketJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue representment packet generation",
    response_description="A job id to poll for the rendered packet.",
)
def request_packet(
    dispute_id: str,
    payload: ScoreRequest,
    request: Request,
    background: BackgroundTasks,
) -> PacketJobAccepted:
    """Queue packet generation for a dispute.

    The dispute is scored first, and a packet is queued **only if the decision
    was CONTEST**. Building a representment for a dispute the policy conceded
    would burn an LLM call on a document nobody will file, and -- more
    importantly -- would blur the one-way boundary between deciding and
    documenting.

    Raises:
        HTTPException: 409 when the decision was ACCEPT, carrying the deciding
            reason so the caller knows why.
    """
    dispute, bundle = build_inputs(payload)

    if dispute.dispute_id != dispute_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"path dispute_id {dispute_id!r} does not match the payload's "
                f"{dispute.dispute_id!r}"
            ),
        )

    decision = score_dispute(dispute, bundle, request)
    if decision.action is not DecisionAction.CONTEST:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"decision for {dispute_id} was ACCEPT ({decision.deciding_reason}); "
                f"no representment packet is generated for conceded disputes"
            ),
        )

    job = job_store.create(dispute.dispute_id)
    background.add_task(_render_packet_job, job.job_id, dispute, bundle)

    return PacketJobAccepted(
        job_id=job.job_id,
        dispute_id=dispute.dispute_id,
        status="queued",
        poll_url=f"/v1/disputes/jobs/{job.job_id}",
    )


@router.get(
    "/jobs/{job_id}",
    response_model=PacketJobState,
    summary="Poll a packet-generation job",
)
def packet_job(job_id: str) -> PacketJobState:
    """Return the current state of a packet job.

    Raises:
        HTTPException: 404 when the job id is unknown or has been evicted.
    """
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no packet job {job_id!r}; jobs are in-process and do not "
            f"survive a restart",
        )

    return PacketJobState(
        job_id=job.job_id,
        dispute_id=job.dispute_id,
        status=job.status,  # type: ignore[arg-type]
        created_at=job.created_at,
        completed_at=job.completed_at,
        packet=job.packet,
        error=job.error,
    )
