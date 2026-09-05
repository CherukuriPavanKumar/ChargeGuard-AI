"""Preset simulation route.

Three hand-built cases, each chosen to exercise a *different decision path*:

===========================  ====================  =============================
preset                        outcome               decided by
===========================  ====================  =============================
``electronics-fraud``         CONTEST               ``strong_evidence`` gate
``low-value-subscription``    ACCEPT                the EV rule
``fraud-ring``                ACCEPT                ``no_pod_on_non_receipt`` gate
===========================  ====================  =============================

That spread is the point.  A demo where every case is decided the same way
proves nothing about the policy layer; these three show a hard CONTEST override,
a pure economic comparison, and a hard ACCEPT override respectively.

MIRROR: ``frontend/src/lib/presets.js`` carries the same three cases so the
simulator works as a static deploy with no API reachable.  The two must agree.
The frontend copy is annotated with the same identifiers.

Timestamps are computed relative to the current clock at request time so the
presets are always live rather than expiring the day after they were written.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from sentinel.api.routes.disputes import (
    PacketJobAccepted,
    _render_packet_job,
    job_store,
    score_dispute,
)
from sentinel.config import get_settings
from sentinel.features import builder
from sentinel.ingest.evidence_loader import assemble
from sentinel.ingest.webhook import parse_dispute_webhook, to_webhook_envelope
from sentinel.packet import renderer
from sentinel.policy import economics, engine
from sentinel.schemas.decision import Decision, DecisionAction
from sentinel.schemas.dispute import DisputeEvent
from sentinel.schemas.evidence import EvidenceBundle

router = APIRouter(prefix="/v1/simulate", tags=["simulate"])


class PresetSummary(BaseModel):
    """Catalogue entry for one preset."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., description="Path segment identifying this preset.")
    label: str = Field(..., description="Display name.")
    amount_inr: float = Field(..., description="Disputed amount.")
    reason_code: str = Field(..., description="Scheme reason code.")
    narrative: str = Field(..., description="What this case is meant to show.")
    expected_path: str = Field(
        ..., description="Which decision path this preset is built to exercise."
    )


class SimulationResponse(BaseModel):
    """A fully traced decision for one preset.

    Carries more than the bare Decision because the simulator UI renders the
    inputs, the calibration comparison, and the packet preview alongside it.
    Everything here is derived from the same objects the production path
    produces -- nothing is synthesised for display.
    """

    model_config = ConfigDict(extra="forbid")

    preset: PresetSummary = Field(..., description="Which preset was run.")
    decision: Decision = Field(
        ..., description="The real Decision, as returned by /v1/disputes/score."
    )
    explanation: str = Field(
        ..., description="Plain-English rendering of the decision."
    )
    raw_score: float = Field(
        ...,
        description=(
            "Uncalibrated booster output. Shown beside the calibrated value so "
            "the effect of isotonic regression is visible. Never used to decide."
        ),
    )
    calibrated_probability: float = Field(
        ..., description="The p_win the policy engine actually consumed."
    )
    isotonic_probability: float = Field(
        ...,
        description=(
            "What the fitted isotonic map would have produced. Equal to the "
            "shipped value when isotonic won the held-out selection; otherwise "
            "the counterfactual. Diagnostics only -- never decides anything."
        ),
    )
    calibration_mode: str = Field(
        ...,
        description=(
            "Which map shipped: 'isotonic' or 'identity'. Selected by held-out "
            "Brier score at training time, not assumed."
        ),
    )
    threshold_at_amount: float = Field(
        ..., description="Break-even probability lambda*c/A for this amount."
    )
    threshold_reachable: bool = Field(
        ...,
        description="False when lambda*c/A exceeds 1 and ACCEPT is forced by arithmetic.",
    )
    features: dict[str, float] = Field(
        ..., description="The exact 35 feature values fed to the model."
    )
    evidence: dict[str, Any] = Field(
        ..., description="Compact evidentiary position of the bundle."
    )
    packet_preview: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Rendered representment excerpt, present only when the decision was "
            "CONTEST. Generated after the decision and unable to influence it."
        ),
    )
    webhook_example: dict[str, Any] = Field(
        ...,
        description="The acquirer envelope this preset corresponds to, for docs.",
    )


# --------------------------------------------------------------------------- #
# Preset construction                                                         #
# --------------------------------------------------------------------------- #


def _electronics_fraud(now: datetime) -> tuple[dict, dict, dict, dict, dict]:
    """INR 32,000 electronics, 3-D Secure authenticated, airtight delivery proof.

    Built to fire ``strong_evidence_gate``: the POD is VERIFIED, a signature was
    captured, and the recipient name matches the cardholder exactly. The model's
    score is deliberately not the deciding factor -- on a INR 32 000 dispute with
    compelling evidence, deferring to a probabilistic score would be the
    expensive mistake.
    """
    placed = now - timedelta(days=34)
    delivered = placed + timedelta(days=3, hours=4)
    raised = now - timedelta(days=3)

    dispute = {
        "id": "dp_preset_electronics",
        "payment_id": "pay_preset_electronics",
        "merchant_id": "acc_0031",
        "amount": 3_200_000,  # paise
        "currency": "INR",
        "reason_code": "VISA_10.4",
        "network": "VISA",
        "created_at": int(raised.timestamp()),
        "respond_by": int((now + timedelta(days=11)).timestamp()),
    }
    order = {
        "order_id": "ord_preset_electronics",
        "customer_name": "Ananya Iyer",
        "billing_address": "Flat 902, Orchid Towers, Residency Road, Bengaluru, Karnataka 560025",
        "shipping_address": "Flat 902, Orchid Towers, Residency Road, Bengaluru, Karnataka 560025",
        "placed_at": placed.isoformat(),
        "items": ["4K Action Camera", "Noise Cancelling Headphones"],
        "order_total": "32000.00",
        "avs_match": True,
        "cvv_match": True,
        "three_ds_status": "AUTHENTICATED",
    }
    session = {
        "ip_address": "49.207.184.22",
        "ip_geo_lat": 12.9716,
        "ip_geo_lon": 77.5946,
        "device_fingerprint": "dev_a91f4c73b8e25d10",
        "user_agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
            "Mobile/15E148 Safari/604.1"
        ),
        "login_at": (placed - timedelta(minutes=18)).isoformat(),
        "account_created_at": (placed - timedelta(days=612)).isoformat(),
    }
    pod = {
        "awb_number": "BLU4471902238",
        "delivered_at": delivered.isoformat(),
        "recipient_name": "Ananya Iyer",
        "signature_captured": True,
        "delivery_address": "Flat 902, Orchid Towers, Residency Road, Bengaluru, Karnataka 560025",
        "carrier": "BLUEDART",
        "scan_count": 9,
        "ocr_confidence": 0.94,
        "extraction_status": "VERIFIED",
    }
    extras = {
        "prior_dispute_count": 0,
        "refund_requested": False,
        "merchant_comms_count": 3,
    }
    return dispute, order, session, pod, extras


def _low_value_subscription(now: datetime) -> tuple[dict, dict, dict, dict, dict]:
    """INR 450 subscription renewal. The per-dispute threshold does the work.

    Built to be decided by the **EV rule**, not by a gate. At c = 350 and
    lambda = 1.2 the break-even probability is 1.2 * 350 / 450 = 0.933: this
    dispute must be all but certain to be worth contesting. No realistic
    evidence position clears that, so the arithmetic concedes it.

    Note the amount sits *above* the representment cost, so
    ``amount_below_cost_gate`` does not fire. This is the case that shows the
    threshold rule operating on its own.
    """
    placed = now - timedelta(days=52)
    raised = now - timedelta(days=6)

    dispute = {
        "id": "dp_preset_subscription",
        "payment_id": "pay_preset_subscription",
        "merchant_id": "acc_0008",
        "amount": 45_000,  # paise
        "currency": "INR",
        "reason_code": "VISA_13.6",
        "network": "VISA",
        "created_at": int(raised.timestamp()),
        "respond_by": int((now + timedelta(days=8)).timestamp()),
    }
    order = {
        "order_id": "ord_preset_subscription",
        "customer_name": "Rahul Mehta",
        "billing_address": "Flat 214, Green Meadows, SV Road, Mumbai, Maharashtra 400058",
        "shipping_address": "Flat 214, Green Meadows, SV Road, Mumbai, Maharashtra 400058",
        "placed_at": placed.isoformat(),
        "items": ["Monthly Subscription Renewal"],
        "order_total": "450.00",
        "avs_match": True,
        "cvv_match": True,
        "three_ds_status": "NOT_ENROLLED",
    }
    session = {
        "ip_address": "103.21.58.194",
        "ip_geo_lat": 19.0760,
        "ip_geo_lon": 72.8777,
        "device_fingerprint": "dev_5c2e08a7d41b9f36",
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "login_at": (placed - timedelta(minutes=6)).isoformat(),
        "account_created_at": (placed - timedelta(days=418)).isoformat(),
    }
    # Digital goods: nothing was shipped, so there is no POD to hold. This is
    # ABSENT rather than UNVERIFIED, and correctly so.
    pod = None
    extras = {
        "prior_dispute_count": 1,
        "refund_requested": False,
        "merchant_comms_count": 1,
    }
    return dispute, order, session, pod, extras


def _fraud_ring(now: datetime) -> tuple[dict, dict, dict, dict, dict]:
    """INR 8,900 not-received claim from a device seen across many accounts.

    Built to fire ``no_pod_on_non_receipt_gate``. The behavioural signals scream
    organised abuse -- a device fingerprint shared across a ring, an account
    minted hours before the order, an offshore checkout IP, four prior disputes
    -- and none of that matters, because under Visa 13.1 proof of delivery is
    the evidence the scheme requires and there is none.

    This preset makes an uncomfortable point deliberately: the system concedes a
    dispute it is confident is fraudulent, because being right is not the same
    as being able to prove it under the rulebook.
    """
    placed = now - timedelta(days=21)
    raised = now - timedelta(days=2)

    dispute = {
        "id": "dp_preset_fraudring",
        "payment_id": "pay_preset_fraudring",
        "merchant_id": "acc_0017",
        "amount": 890_000,  # paise
        "currency": "INR",
        "reason_code": "VISA_13.1",
        "network": "VISA",
        "created_at": int(raised.timestamp()),
        "respond_by": int((now + timedelta(days=13)).timestamp()),
    }
    order = {
        "order_id": "ord_preset_fraudring",
        "customer_name": "Imran Khan",
        "billing_address": "Flat 118, Crystal Court, Ring Road, Delhi, Delhi 110024",
        "shipping_address": "Flat 704, Palm Grove, Station Road, Jaipur, Rajasthan 302017",
        "placed_at": placed.isoformat(),
        "items": ["Mechanical Keyboard", "Gaming Mouse", "Bluetooth Speaker"],
        "order_total": "8900.00",
        "avs_match": False,
        "cvv_match": True,
        "three_ds_status": "ATTEMPTED",
    }
    session = {
        "ip_address": "185.220.101.47",
        "ip_geo_lat": 25.2048,
        "ip_geo_lon": 55.2708,  # Dubai -- offshore
        "device_fingerprint": "dev_ring_07_3f9a1c4e88b2",
        "user_agent": (
            "Mozilla/5.0 (Linux; Android 13; RMX3771) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0 Mobile Safari/537.36"
        ),
        "login_at": (placed - timedelta(seconds=38)).isoformat(),
        "account_created_at": (placed - timedelta(hours=5)).isoformat(),
    }
    pod = None
    extras = {
        "prior_dispute_count": 4,
        "refund_requested": False,
        "merchant_comms_count": 0,
    }
    return dispute, order, session, pod, extras


#: Preset catalogue. Keys are the path segments accepted by the route.
PRESETS: dict[str, dict[str, Any]] = {
    "electronics-fraud": {
        "label": "INR 32,000 Electronics Fraud",
        "narrative": (
            "High value, airtight delivery proof, 3-D Secure authenticated. The "
            "compelling-evidence gate contests this regardless of model score."
        ),
        "expected_path": "CONTEST via strong_evidence gate",
        "build": _electronics_fraud,
    },
    "low-value-subscription": {
        "label": "INR 450 Low-Value Subscription",
        "narrative": (
            "Above the representment cost, so no gate fires. The per-dispute "
            "threshold demands 93.3% confidence and the arithmetic concedes."
        ),
        "expected_path": "ACCEPT via EV rule",
        "build": _low_value_subscription,
    },
    "fraud-ring": {
        "label": "Fraud Ring Syndicate",
        "narrative": (
            "Shared device fingerprint, hours-old account, offshore IP, four "
            "prior disputes -- and no proof of delivery. Unwinnable under Visa "
            "13.1 whatever we suspect."
        ),
        "expected_path": "ACCEPT via no_pod_on_non_receipt gate",
        "build": _fraud_ring,
    },
}


def build_preset(key: str) -> tuple[DisputeEvent, EvidenceBundle, PresetSummary]:
    """Materialise a preset into a dispute and an evidence bundle.

    Raises:
        HTTPException: 404 for an unknown preset key.
    """
    spec = PRESETS.get(key)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown preset {key!r}; available: {sorted(PRESETS)}",
        )

    now = datetime.now(timezone.utc)
    dispute_payload, order, session, pod, extras = spec["build"](now)

    dispute = parse_dispute_webhook(dispute_payload)
    bundle = assemble(
        order_payload=order,
        session_payload=session,
        pod_image_path=None,
        pod_record=pod,
        settings=get_settings(),
        **extras,
    )

    summary = PresetSummary(
        key=key,
        label=spec["label"],
        amount_inr=float(dispute.amount_inr),
        reason_code=dispute.reason_code.value,
        narrative=spec["narrative"],
        expected_path=spec["expected_path"],
    )
    return dispute, bundle, summary


@router.get(
    "",
    response_model=list[PresetSummary],
    summary="List the available simulation presets",
)
def list_presets() -> list[PresetSummary]:
    """Return the preset catalogue without running any of them."""
    return [build_preset(key)[2] for key in PRESETS]


@router.get(
    "/{preset}",
    response_model=SimulationResponse,
    summary="Run a preset through the full decision pipeline",
    response_description=(
        "The real Decision plus its inputs, calibration comparison and, when "
        "the decision was CONTEST, a representment preview."
    ),
)
def simulate(preset: str, request: Request) -> SimulationResponse:
    """Run one preset end to end and return everything the simulator renders.

    The decision comes from the same :func:`score_dispute` the production route
    uses. The packet, when present, is generated **after** the decision from a
    builder that never sees it.
    """
    dispute, bundle, summary = build_preset(preset)
    decision = score_dispute(dispute, bundle, request)

    settings = get_settings()
    model = request.app.state.model
    features = builder.build(dispute, bundle)

    threshold = economics.decision_threshold(
        dispute.amount_inr, settings.representment_cost_inr, settings.risk_margin
    )

    packet_preview: dict[str, Any] | None = None
    if decision.action.value == "CONTEST":
        packet = renderer.build_packet(
            dispute, bundle, settings, write_to_disk=False
        )
        packet_preview = {
            "summary": packet.summary,
            "evidence_narrative": packet.evidence_narrative,
            "scheme_argument": packet.scheme_argument,
            "cited_artifacts": list(packet.cited_artifacts),
            "source": packet.source.value,
            "html": packet.html,
            "pdf_available": packet.pdf_path is not None,
        }

    return SimulationResponse(
        preset=summary,
        decision=decision,
        explanation=engine.explain(decision, settings),
        raw_score=round(model.raw_score(features), 6),
        calibrated_probability=round(decision.win_probability, 6),
        isotonic_probability=round(model.isotonic_counterfactual(features), 6),
        calibration_mode=model.calibration_mode,
        threshold_at_amount=round(threshold, 6),
        threshold_reachable=economics.is_threshold_reachable(threshold),
        features=features.to_flat_dict(),
        evidence=renderer.evidence_summary(bundle),
        packet_preview=packet_preview,
        webhook_example=to_webhook_envelope(dispute),
    )


@router.post(
    "/{preset}/packet",
    response_model=PacketJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue packet generation for a preset",
    response_description="A job id to poll at /v1/disputes/jobs/{job_id}.",
)
def simulate_packet(
    preset: str, request: Request, background: BackgroundTasks
) -> PacketJobAccepted:
    """Queue a real representment packet job for a preset case.

    Exists so the UI can exercise the genuine asynchronous path -- queue, poll,
    render -- rather than showing a progress bar over a synchronous call. The
    packet the simulate endpoint returns inline is a *preview* rendered in
    memory; this one runs the same background job the production route uses,
    including the PDF attempt.

    Raises:
        HTTPException: 409 when the preset's decision was ACCEPT. Building a
            representment for a conceded dispute would blur the one-way boundary
            between deciding and documenting.
    """
    dispute, bundle, _summary = build_preset(preset)
    decision = score_dispute(dispute, bundle, request)

    if decision.action is not DecisionAction.CONTEST:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"decision for preset {preset!r} was ACCEPT "
                f"({decision.deciding_reason}); no packet is generated for "
                f"conceded disputes"
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
