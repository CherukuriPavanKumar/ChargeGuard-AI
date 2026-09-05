"""Shared fixtures.

Design note: the factories below build objects from **explicit keyword
overrides on a known-good baseline**, rather than from randomised or minimal
data.  A gate test that says ``make_bundle(three_ds=ThreeDSStatus.FAILED)`` reads
as the single fact under test, and any other fact the gate depends on is
visibly held constant.

Nothing here reads the corpus on disk except where a test explicitly needs the
trained artifacts, so the bulk of the suite runs on a clean checkout before
``make data`` has ever executed.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

#: ``backend/`` -- the repository's Python root. Added to ``sys.path`` so tests
#: import ``sentinel``, ``data_gen`` and ``eval`` the same way the Makefile
#: targets do, without requiring an editable install.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
for entry in (str(BACKEND_ROOT / "src"), str(BACKEND_ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from sentinel.config import Settings  # noqa: E402
from sentinel.schemas.dispute import (  # noqa: E402
    CardNetwork,
    DisputeEvent,
    ReasonCode,
)
from sentinel.schemas.evidence import (  # noqa: E402
    Carrier,
    EvidenceBundle,
    ExtractionStatus,
    OrderRecord,
    ProofOfDelivery,
    SessionLog,
    ThreeDSStatus,
)

#: The anchor every constructed fixture hangs off, resolved once at import.
#:
#: Anchored to the real clock rather than to a frozen literal, and deliberately
#: so: ``expired_window_gate`` reads the wall clock, which is correct policy
#: behaviour. A fixture pinned to a fixed past date would make every dispute in
#: the suite expired, and that one gate would then pre-empt every other test.
#:
#: This does not compromise determinism. Every model-visible feature is a
#: *difference* between two timestamps and is invariant to where the anchor
#: sits; only ``hours_remaining`` moves, which is exactly the quantity these
#: fixtures need to keep live. It is the same reasoning that governs the corpus
#: rebase in ``data_gen.seeds``.
NOW = datetime.now(timezone.utc)

#: Distinguishes "argument not supplied" from an explicit ``None``. Needed
#: because ``delivered_at=None`` is a meaningful value -- an illegible delivery
#: timestamp -- and a plain ``or`` default would silently discard it.
_UNSET = object()

#: Baseline address used on both sides of the order unless a test diverges them.
ADDRESS = "Flat 902, Orchid Towers, Residency Road, Bengaluru, Karnataka 560025"

#: Baseline cardholder name.
CUSTOMER = "Ananya Iyer"


@pytest.fixture
def settings() -> Settings:
    """Settings with the shipped defaults: c = 350, lambda = 1.2."""
    return Settings()


@pytest.fixture
def make_dispute():
    """Factory for :class:`DisputeEvent` with a live representment window."""

    def _make(
        amount: str | Decimal = "5000.00",
        reason_code: ReasonCode = ReasonCode.VISA_13_1,
        network: CardNetwork = CardNetwork.VISA,
        hours_remaining: float = 240.0,
        window_hours: float = 336.0,
        dispute_id: str = "dp_test_0001",
    ) -> DisputeEvent:
        respond_by = NOW + timedelta(hours=hours_remaining)
        return DisputeEvent(
            dispute_id=dispute_id,
            transaction_id="txn_test_0001",
            merchant_id="acc_test",
            reason_code=reason_code,
            amount_inr=Decimal(str(amount)),
            currency="INR",
            disputed_at=respond_by - timedelta(hours=window_hours),
            respond_by=respond_by,
            network=network,
        )

    return _make


@pytest.fixture
def make_pod():
    """Factory for :class:`ProofOfDelivery` in any extraction state."""

    def _make(
        status: ExtractionStatus = ExtractionStatus.VERIFIED,
        signature: bool = True,
        recipient: str = CUSTOMER,
        address: str = ADDRESS,
        confidence: float = 0.93,
        scan_count: int = 7,
        delivered_at: datetime | None | object = _UNSET,
    ) -> ProofOfDelivery:
        if status is ExtractionStatus.ABSENT:
            return ProofOfDelivery(extraction_status=ExtractionStatus.ABSENT)
        resolved = (
            NOW - timedelta(days=30) if delivered_at is _UNSET else delivered_at
        )
        return ProofOfDelivery(
            awb_number="BLU1234567890",
            delivered_at=resolved,
            recipient_name=recipient,
            signature_captured=signature,
            delivery_address=address,
            carrier=Carrier.BLUEDART,
            scan_count=scan_count,
            ocr_confidence=confidence,
            extraction_status=status,
        )

    return _make


@pytest.fixture
def make_bundle(make_pod):
    """Factory for a complete :class:`EvidenceBundle`."""

    def _make(
        pod: ProofOfDelivery | None = None,
        three_ds: ThreeDSStatus = ThreeDSStatus.AUTHENTICATED,
        avs: bool = True,
        cvv: bool = True,
        billing: str = ADDRESS,
        shipping: str = ADDRESS,
        customer: str = CUSTOMER,
        order_total: str = "5000.00",
        prior_disputes: int = 0,
        refund_requested: bool = False,
        comms: int = 2,
        account_age_days: float = 400.0,
        login_minutes_before: float = 12.0,
    ) -> EvidenceBundle:
        placed_at = NOW - timedelta(days=40)
        return EvidenceBundle(
            pod=pod if pod is not None else make_pod(),
            order=OrderRecord(
                order_id="ord_test_0001",
                customer_name=customer,
                billing_address=billing,
                shipping_address=shipping,
                placed_at=placed_at,
                items=("Wireless Earbuds (ANC)", "Laptop Backpack"),
                order_total=Decimal(order_total),
                avs_match=avs,
                cvv_match=cvv,
                three_ds_status=three_ds,
            ),
            session=SessionLog(
                ip_address="49.207.184.22",
                ip_geo_lat=12.9716,
                ip_geo_lon=77.5946,
                device_fingerprint="dev_test_a91f4c73b8e2",
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
                ),
                login_at=placed_at - timedelta(minutes=login_minutes_before),
                account_created_at=placed_at - timedelta(days=account_age_days),
            ),
            prior_dispute_count=prior_disputes,
            refund_requested=refund_requested,
            merchant_comms_count=comms,
        )

    return _make


@pytest.fixture
def base_dispute(make_dispute) -> DisputeEvent:
    """A INR 5,000 not-received dispute with 240 hours left to respond."""
    return make_dispute()


@pytest.fixture
def base_bundle(make_bundle) -> EvidenceBundle:
    """A strong bundle: verified signed POD, matching name, 3-D Secure."""
    return make_bundle()


@pytest.fixture
def base_features(base_dispute, base_bundle):
    """The feature vector for the baseline dispute and bundle."""
    from sentinel.features import builder

    return builder.build(base_dispute, base_bundle)


@pytest.fixture
def artifacts_available() -> bool:
    """True when trained model artifacts exist on disk."""
    from sentinel.models.win_probability import (
        BOOSTER_FILENAME,
        CALIBRATOR_FILENAME,
    )

    artifacts = Settings().artifacts_dir
    return (artifacts / BOOSTER_FILENAME).is_file() and (
        artifacts / CALIBRATOR_FILENAME
    ).is_file()


@pytest.fixture
def trained_model(artifacts_available):
    """The loaded win-probability model, or skip if it has not been trained.

    Skipped rather than failed so the suite is meaningful on a clean checkout
    before ``make data && make train`` has run. ``make all`` runs those first,
    so in the canonical flow this never skips.
    """
    if not artifacts_available:
        pytest.skip("model artifacts absent; run `make data && make train`")

    from sentinel.models.win_probability import WinProbabilityModel

    return WinProbabilityModel.load(Settings())
