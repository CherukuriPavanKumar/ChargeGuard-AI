"""Schema contract enforcement.

Three properties, asserted across every value object in the system:

**``extra="forbid"``** -- an unknown field is a rejected payload, not a silently
dropped one. A typo'd ``amount_paise`` where ``amount_inr`` was meant must fail
loudly at the boundary rather than defaulting somewhere downstream.

**``frozen=True``** -- a dispute event and a decision are historical facts.
Mutating one after the fact would leave the audit trail describing something
that never happened.

**Field constraints** -- negative amounts, out-of-range probabilities, and
malformed enums are rejected at construction. These are the boundary conditions
that would otherwise propagate into an expected-value computation and produce a
confidently wrong rupee figure.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from sentinel.schemas.decision import DecisionAction, GateResult
from sentinel.schemas.dispute import CardNetwork, DisputeEvent, ReasonCode
from sentinel.schemas.evidence import (
    Carrier,
    EvidenceBundle,
    ExtractionStatus,
    OrderRecord,
    ProofOfDelivery,
    SessionLog,
    ThreeDSStatus,
)
from sentinel.schemas.features import FeatureVector

NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


class TestExtraForbid:
    def test_dispute_rejects_an_unknown_field(self, make_dispute):
        payload = make_dispute().model_dump()
        payload["amount_paise"] = 500_000

        with pytest.raises(ValidationError) as exc:
            DisputeEvent.model_validate(payload)
        assert "amount_paise" in str(exc.value)

    def test_pod_rejects_an_unknown_field(self):
        with pytest.raises(ValidationError):
            ProofOfDelivery(
                extraction_status=ExtractionStatus.ABSENT,
                courier_name="Delhivery",  # not a field; carrier is
            )

    def test_order_rejects_an_unknown_field(self, base_bundle):
        payload = base_bundle.order.model_dump()
        payload["discount_code"] = "SAVE20"

        with pytest.raises(ValidationError):
            OrderRecord.model_validate(payload)

    def test_session_rejects_an_unknown_field(self, base_bundle):
        payload = base_bundle.session.model_dump()
        payload["referrer"] = "https://example.com"

        with pytest.raises(ValidationError):
            SessionLog.model_validate(payload)

    def test_bundle_rejects_an_unknown_field(self, base_bundle):
        payload = base_bundle.model_dump()
        payload["chargeback_count"] = 3

        with pytest.raises(ValidationError):
            EvidenceBundle.model_validate(payload)

    def test_feature_vector_rejects_an_unknown_field(self, base_features):
        payload = base_features.model_dump()
        payload["experimental_feature"] = 1.0

        with pytest.raises(ValidationError):
            FeatureVector.model_validate(payload)

    def test_gate_result_rejects_an_unknown_field(self):
        with pytest.raises(ValidationError):
            GateResult(
                gate_name="x",
                fired=False,
                rationale="y",
                severity="high",  # not a field
            )


class TestFrozen:
    def test_dispute_rejects_mutation(self, base_dispute):
        """A dispute event is a historical fact, not a mutable row."""
        with pytest.raises(ValidationError):
            base_dispute.amount_inr = Decimal("999999")

    def test_pod_rejects_mutation(self, base_bundle):
        with pytest.raises(ValidationError):
            base_bundle.pod.signature_captured = False

    def test_order_rejects_mutation(self, base_bundle):
        with pytest.raises(ValidationError):
            base_bundle.order.three_ds_status = ThreeDSStatus.AUTHENTICATED

    def test_bundle_rejects_mutation(self, base_bundle):
        with pytest.raises(ValidationError):
            base_bundle.prior_dispute_count = 99

    def test_feature_vector_rejects_mutation(self, base_features):
        with pytest.raises(ValidationError):
            base_features.amount_inr = 1.0

    def test_order_items_are_a_tuple_not_a_list(self, base_bundle):
        """Immutability must be real, not merely assignment-proof.

        A frozen model holding a list still lets a caller append to it. Items
        are a tuple so the object is genuinely immutable all the way down.
        """
        assert isinstance(base_bundle.order.items, tuple)
        with pytest.raises(AttributeError):
            base_bundle.order.items.append("smuggled item")  # type: ignore[attr-defined]

    def test_model_copy_produces_a_new_object(self, base_dispute):
        """The supported way to derive a variant leaves the original untouched."""
        derived = base_dispute.model_copy(update={"amount_inr": Decimal("777")})

        assert derived.amount_inr == Decimal("777")
        assert base_dispute.amount_inr != Decimal("777")
        assert derived is not base_dispute


class TestAmountConstraints:
    @pytest.mark.parametrize("amount", ["0", "-1", "-9999.99"])
    def test_rejects_non_positive_disputed_amount(self, amount, make_dispute):
        """A dispute for zero or negative rupees is not a dispute."""
        payload = make_dispute().model_dump()
        payload["amount_inr"] = Decimal(amount)

        with pytest.raises(ValidationError) as exc:
            DisputeEvent.model_validate(payload)
        assert "amount_inr" in str(exc.value)

    @pytest.mark.parametrize("total", ["0", "-500"])
    def test_rejects_non_positive_order_total(self, total, base_bundle):
        payload = base_bundle.order.model_dump()
        payload["order_total"] = Decimal(total)

        with pytest.raises(ValidationError):
            OrderRecord.model_validate(payload)

    def test_accepts_the_smallest_meaningful_amount(self, make_dispute):
        dispute = make_dispute(amount="0.01")
        assert dispute.amount_inr == Decimal("0.01")

    def test_amount_precision_survives_a_json_round_trip(self, make_dispute):
        """Rupee precision must not degrade through serialisation.

        The amount is the number every economic computation multiplies; a
        float round trip would introduce error into all of them.
        """
        dispute = make_dispute(amount="2400.55")
        restored = DisputeEvent.model_validate_json(dispute.model_dump_json())
        assert restored.amount_inr == Decimal("2400.55")


class TestRangeConstraints:
    @pytest.mark.parametrize("confidence", [-0.01, 1.01, 2.0])
    def test_rejects_ocr_confidence_outside_the_unit_interval(self, confidence):
        with pytest.raises(ValidationError):
            ProofOfDelivery(
                ocr_confidence=confidence,
                extraction_status=ExtractionStatus.VERIFIED,
            )

    def test_rejects_negative_scan_count(self):
        with pytest.raises(ValidationError):
            ProofOfDelivery(
                scan_count=-1, extraction_status=ExtractionStatus.VERIFIED
            )

    @pytest.mark.parametrize("lat", [-91.0, 91.0])
    def test_rejects_out_of_range_latitude(self, lat, base_bundle):
        payload = base_bundle.session.model_dump()
        payload["ip_geo_lat"] = lat

        with pytest.raises(ValidationError):
            SessionLog.model_validate(payload)

    @pytest.mark.parametrize("lon", [-181.0, 181.0])
    def test_rejects_out_of_range_longitude(self, lon, base_bundle):
        payload = base_bundle.session.model_dump()
        payload["ip_geo_lon"] = lon

        with pytest.raises(ValidationError):
            SessionLog.model_validate(payload)

    def test_rejects_negative_prior_dispute_count(self, base_bundle):
        payload = base_bundle.model_dump()
        payload["prior_dispute_count"] = -1

        with pytest.raises(ValidationError):
            EvidenceBundle.model_validate(payload)


class TestEnumConstraints:
    def test_rejects_an_unrecognised_reason_code(self, make_dispute):
        payload = make_dispute().model_dump()
        payload["reason_code"] = "VISA_99.9"

        with pytest.raises(ValidationError):
            DisputeEvent.model_validate(payload)

    def test_rejects_an_unrecognised_three_ds_status(self, base_bundle):
        payload = base_bundle.order.model_dump()
        payload["three_ds_status"] = "MAYBE"

        with pytest.raises(ValidationError):
            OrderRecord.model_validate(payload)

    def test_reason_codes_cover_the_specified_vocabulary(self):
        """Every reason code the design names must exist."""
        values = {code.value for code in ReasonCode}
        assert values == {
            "VISA_10.4",
            "VISA_13.1",
            "VISA_13.3",
            "VISA_13.6",
            "MC_4837",
            "MC_4853",
        }

    def test_decision_action_is_binary(self):
        """No ESCALATE, no REVIEW. A third option would defer the question."""
        assert {a.value for a in DecisionAction} == {"CONTEST", "ACCEPT"}

    def test_extraction_status_covers_all_four_states(self):
        assert {s.value for s in ExtractionStatus} == {
            "VERIFIED",
            "LOW_CONFIDENCE",
            "UNVERIFIED",
            "ABSENT",
        }

    def test_carrier_vocabulary_matches_the_rendered_templates(self):
        """Every carrier with a POD template must be in the enum."""
        from data_gen.pod_renderer import TEMPLATES

        assert set(TEMPLATES.keys()) <= set(Carrier)
        assert len(TEMPLATES) == 4


class TestComputedProperties:
    def test_hours_remaining_is_positive_for_a_live_dispute(self, make_dispute):
        dispute = make_dispute(hours_remaining=100_000.0)
        assert dispute.hours_remaining > 0

    def test_hours_remaining_is_negative_after_the_deadline(self, make_dispute):
        dispute = make_dispute(hours_remaining=-10_000.0)
        assert dispute.hours_remaining < 0

    def test_window_hours_is_clock_free(self, make_dispute):
        """Computed from two fields on the event, so the builder may consume it."""
        dispute = make_dispute(window_hours=336.0)
        assert dispute.window_hours == pytest.approx(336.0, abs=1e-6)

    def test_reason_code_classification_helpers(self, make_dispute):
        assert make_dispute(reason_code=ReasonCode.VISA_10_4).is_fraud_code
        assert make_dispute(reason_code=ReasonCode.MC_4837).is_fraud_code
        assert not make_dispute(reason_code=ReasonCode.VISA_13_1).is_fraud_code

        assert make_dispute(reason_code=ReasonCode.VISA_13_1).is_non_receipt_code
        assert make_dispute(reason_code=ReasonCode.MC_4853).is_non_receipt_code
        assert not make_dispute(reason_code=ReasonCode.VISA_13_6).is_non_receipt_code

    def test_liability_shift_only_on_authenticated(self, make_bundle):
        for status in ThreeDSStatus:
            bundle = make_bundle(three_ds=status)
            expected = status is ThreeDSStatus.AUTHENTICATED
            assert bundle.order.liability_shifted is expected

    def test_pod_usability_excludes_absent_and_unverified(self, make_pod):
        assert make_pod(status=ExtractionStatus.VERIFIED).is_usable
        assert make_pod(status=ExtractionStatus.LOW_CONFIDENCE).is_usable
        assert not make_pod(status=ExtractionStatus.UNVERIFIED).is_usable
        assert not make_pod(status=ExtractionStatus.ABSENT).is_usable

    def test_mobile_detection_from_user_agent(self, base_bundle):
        assert base_bundle.session.is_mobile is True

        desktop = base_bundle.session.model_copy(
            update={
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
                )
            }
        )
        assert desktop.is_mobile is False


class TestSerialisation:
    def test_decimal_amounts_serialise_as_json_numbers(self, make_dispute):
        """The frontend does arithmetic on these; strings would concatenate."""
        payload = make_dispute(amount="2400.50").model_dump(mode="json")
        assert isinstance(payload["amount_inr"], float)
        assert payload["amount_inr"] == 2400.50

    def test_bundle_round_trips_through_json(self, base_bundle):
        restored = EvidenceBundle.model_validate_json(base_bundle.model_dump_json())

        assert restored.order.customer_name == base_bundle.order.customer_name
        assert restored.pod.extraction_status is base_bundle.pod.extraction_status
        assert restored.order.items == base_bundle.order.items

    def test_feature_vector_round_trips_exactly(self, base_features):
        """Feature values must survive an audit-log round trip bit for bit."""
        restored = FeatureVector.model_validate_json(
            base_features.model_dump_json()
        )
        assert restored.to_flat_dict() == base_features.to_flat_dict()

    def test_enums_serialise_as_their_string_values(self, make_dispute):
        payload = make_dispute(reason_code=ReasonCode.VISA_13_1).model_dump(
            mode="json"
        )
        assert payload["reason_code"] == "VISA_13.1"
        assert payload["network"] == "VISA"


class TestWebhookBoundary:
    def test_paise_convert_to_rupees_without_float_error(self):
        """``12345`` paise is exactly ``123.45``, not ``123.450000000000003``."""
        from sentinel.ingest.webhook import paise_to_rupees

        assert paise_to_rupees(12345) == Decimal("123.45")
        assert paise_to_rupees(3_200_000) == Decimal("32000.00")
        assert paise_to_rupees(1) == Decimal("0.01")

    def test_fractional_paise_are_rejected(self):
        from sentinel.ingest.webhook import WebhookParseError, paise_to_rupees

        with pytest.raises(WebhookParseError, match="integer"):
            paise_to_rupees(123.5)

    def test_webhook_round_trips_through_the_adapter(self, make_dispute):
        from sentinel.ingest.webhook import (
            parse_dispute_webhook,
            to_webhook_envelope,
        )

        original = make_dispute(amount="8900.00", reason_code=ReasonCode.VISA_13_1)
        restored = parse_dispute_webhook(to_webhook_envelope(original))

        assert restored.dispute_id == original.dispute_id
        assert restored.amount_inr == original.amount_inr
        assert restored.reason_code is original.reason_code
        assert restored.network is original.network

    def test_missing_required_webhook_field_is_rejected(self):
        from sentinel.ingest.webhook import WebhookParseError, parse_dispute_webhook

        with pytest.raises(WebhookParseError, match="missing required field"):
            parse_dispute_webhook({"id": "dp_1", "amount": 100})

    def test_respond_by_before_created_at_is_rejected(self):
        """A window that closes before it opens is a malformed envelope."""
        from sentinel.ingest.webhook import WebhookParseError, parse_dispute_webhook

        with pytest.raises(WebhookParseError, match="must be after"):
            parse_dispute_webhook(
                {
                    "id": "dp_1",
                    "payment_id": "pay_1",
                    "reason_code": "13.1",
                    "amount": 100_000,
                    "created_at": int(NOW.timestamp()),
                    "respond_by": int((NOW - timedelta(days=1)).timestamp()),
                }
            )

    def test_network_is_inferred_from_the_reason_code_when_absent(self):
        from sentinel.ingest.webhook import parse_dispute_webhook

        dispute = parse_dispute_webhook(
            {
                "id": "dp_1",
                "payment_id": "pay_1",
                "reason_code": "13.1",
                "amount": 100_000,
                "created_at": int(NOW.timestamp()),
                "respond_by": int((NOW + timedelta(days=7)).timestamp()),
            }
        )
        assert dispute.network is CardNetwork.VISA

    def test_order_payload_missing_required_fields_is_rejected(self):
        """An evidentiary gap degrades; a missing order record does not."""
        from sentinel.ingest.evidence_loader import EvidenceParseError, parse_order

        with pytest.raises(EvidenceParseError, match="missing required field"):
            parse_order({"order_id": "ord_1"})
