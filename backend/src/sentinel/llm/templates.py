"""Deterministic rebuttal templates -- the fallback that always works.

INVARIANT 6: the packet path degrades, it does not fail.  When the Anthropic API
is unreachable, the key is unset, the model returns unparseable output twice, or
the draft cites an artifact that does not exist, this module produces the
document instead.

The templates are not a stub.  They are reason-code-specific, they cite the same
validated artifact index the model would have cited, and they produce a filing
an issuer would accept.  They are less fluent than a good LLM draft and that is
the entire trade: fluency is nice, and a representment that exists beats a
representment that would have been eloquent.

Design note
-----------
Because these templates are pure string composition over the bundle, they are
also the *reference* for what a correct draft looks like.  The system prompt in
``prompts/rebuttal_system.txt`` asks the model for the same structure and the
same citation discipline, so the two paths produce interchangeable documents and
the renderer needs no branching.
"""

from __future__ import annotations

from sentinel.llm.validators import RebuttalDraft, artifact_index
from sentinel.schemas.dispute import DisputeEvent, ReasonCode
from sentinel.schemas.evidence import EvidenceBundle, ExtractionStatus, ThreeDSStatus

#: Scheme rule text per reason code: the standard the filing must meet.
SCHEME_RULE: dict[ReasonCode, str] = {
    ReasonCode.VISA_13_1: (
        "Visa Core Rules, dispute condition 13.1 (Merchandise or Services Not "
        "Received). The merchant may remedy this dispute by supplying evidence "
        "that the goods were delivered to the cardholder or to the address "
        "provided at the time of the transaction."
    ),
    ReasonCode.VISA_13_3: (
        "Visa Core Rules, dispute condition 13.3 (Not as Described or Defective "
        "Merchandise). The merchant may remedy this dispute by evidencing that "
        "the goods matched their description at the point of sale and that the "
        "disclosed returns policy was made available to the cardholder."
    ),
    ReasonCode.VISA_13_6: (
        "Visa Core Rules, dispute condition 13.6 (Credit Not Processed). The "
        "merchant may remedy this dispute by evidencing that no credit was owed, "
        "or that any credit due has been processed."
    ),
    ReasonCode.VISA_10_4: (
        "Visa Core Rules, dispute condition 10.4 (Other Fraud - Card Absent "
        "Environment). The merchant may remedy this dispute with compelling "
        "evidence under Visa rule 11.4, including evidence of cardholder "
        "participation or of a successful 3-D Secure authentication carrying a "
        "shift of fraud liability to the issuer."
    ),
    ReasonCode.MC_4837: (
        "Mastercard Chargeback Guide, reason code 4837 (No Cardholder "
        "Authorisation). The merchant may remedy this dispute by evidencing "
        "cardholder participation or a successful authentication carrying a "
        "liability shift."
    ),
    ReasonCode.MC_4853: (
        "Mastercard Chargeback Guide, reason code 4853 (Cardholder Dispute). The "
        "merchant may remedy this dispute by evidencing delivery of the goods or "
        "services as described to the cardholder."
    ),
}


def _describe_pod(bundle: EvidenceBundle) -> str:
    """One sentence describing the proof-of-delivery position."""
    pod = bundle.pod
    status = pod.extraction_status

    if status is ExtractionStatus.ABSENT:
        return (
            "No carrier proof-of-delivery document is held against this "
            "consignment."
        )
    if status is ExtractionStatus.UNVERIFIED:
        return (
            "A carrier proof-of-delivery document is held against this "
            "consignment but could not be machine-verified; the original slip "
            "is available on request."
        )

    parts = [
        f"A {pod.carrier.value.title()} proof-of-delivery slip"
        + (f" (waybill {pod.awb_number})" if pod.awb_number else "")
        + " is held against this consignment"
    ]
    if pod.delivered_at is not None:
        parts.append(
            f", recording delivery on {pod.delivered_at.strftime('%d %B %Y at %H:%M')}"
        )
    if pod.recipient_name:
        parts.append(f" and signed for by {pod.recipient_name}")
    if pod.scan_count > 0:
        parts.append(
            f". The carrier network recorded {pod.scan_count} scan events "
            f"tracking the parcel to the delivery address"
        )
    return "".join(parts) + "."


def _describe_authentication(bundle: EvidenceBundle) -> str:
    """One sentence describing the authorisation and authentication position."""
    order = bundle.order
    checks: list[str] = []
    checks.append("AVS matched" if order.avs_match else "AVS did not match")
    checks.append("CVV2 matched" if order.cvv_match else "CVV2 did not match")

    if order.three_ds_status is ThreeDSStatus.AUTHENTICATED:
        auth = (
            "The transaction was authenticated via 3-D Secure, shifting fraud "
            "liability to the issuer"
        )
    elif order.three_ds_status is ThreeDSStatus.ATTEMPTED:
        auth = "3-D Secure authentication was attempted but not completed"
    elif order.three_ds_status is ThreeDSStatus.FAILED:
        auth = "3-D Secure authentication was attempted and failed"
    else:
        auth = "The card was not enrolled in 3-D Secure at the time of the transaction"

    return f"At authorisation, {' and '.join(checks)}. {auth}."


def _describe_behaviour(bundle: EvidenceBundle) -> str:
    """One sentence on the session and account-history position."""
    session = bundle.session
    order = bundle.order

    age_days = (
        order.placed_at.replace(tzinfo=None) - session.account_created_at.replace(tzinfo=None)
    ).total_seconds() / 86400.0

    parts = [
        f"The order was placed from an authenticated session on device "
        f"{session.device_fingerprint[:16]}, from IP {session.ip_address}",
        f", against an account {age_days:,.0f} days old",
    ]
    if bundle.merchant_comms_count > 0:
        parts.append(
            f". The merchant logged {bundle.merchant_comms_count} direct "
            f"communications with the cardholder in relation to this order"
        )
    if bundle.prior_dispute_count > 0:
        parts.append(
            f". This cardholder has raised {bundle.prior_dispute_count} prior "
            f"dispute(s) against this merchant"
        )
    return "".join(parts) + "."


def _summary(dispute: DisputeEvent, bundle: EvidenceBundle) -> str:
    """Compose the case summary paragraph."""
    order = bundle.order
    item_text = (
        ", ".join(order.items[:3]) + ("..." if len(order.items) > 3 else "")
        if order.items
        else "the ordered goods"
    )
    return (
        f"This representment concerns dispute {dispute.dispute_id} against "
        f"transaction {dispute.transaction_id}, raised under {dispute.reason_code} "
        f"for INR {dispute.amount_inr:,.2f}. Order {order.order_id} was placed by "
        f"{order.customer_name} on "
        f"{order.placed_at.strftime('%d %B %Y')} for {item_text}, with a total "
        f"order value of INR {order.order_total:,.2f}, and despatched to the "
        f"address supplied by the cardholder at checkout. The merchant holds "
        f"contemporaneous records evidencing that the transaction was validly "
        f"authorised and that the merchant performed its obligations, and "
        f"respectfully requests that the chargeback be reversed."
    )


def _evidence_narrative(dispute: DisputeEvent, bundle: EvidenceBundle) -> str:
    """Compose the artifact walkthrough."""
    return " ".join(
        (
            _describe_pod(bundle),
            _describe_authentication(bundle),
            _describe_behaviour(bundle),
            f"The shipping address of record is {bundle.order.shipping_address}, "
            f"and the billing address supplied at checkout is "
            f"{bundle.order.billing_address}.",
        )
    )


def _scheme_argument(dispute: DisputeEvent, bundle: EvidenceBundle) -> str:
    """Compose the reason-code-specific legal argument."""
    rule = SCHEME_RULE.get(
        dispute.reason_code,
        "the applicable card-scheme dispute rules for this reason code",
    )

    if dispute.is_non_receipt_code:
        specific = (
            "The carrier documentation submitted with this filing evidences "
            "delivery to the address the cardholder supplied, which is the "
            "remedy the rule contemplates."
        )
    elif dispute.is_fraud_code:
        if bundle.order.liability_shifted:
            specific = (
                "The transaction carries a successful 3-D Secure authentication. "
                "Fraud liability for an authenticated card-absent transaction "
                "rests with the issuer, and the dispute is not properly raised "
                "against the merchant."
            )
        else:
            specific = (
                "The merchant submits the authorisation and session records "
                "below as evidence of cardholder participation in the "
                "transaction."
            )
    elif dispute.reason_code is ReasonCode.VISA_13_6:
        specific = (
            "The merchant's ledger shows no credit outstanding against this "
            "transaction, and no refund was owed under the disclosed terms of "
            "sale."
        )
    else:
        specific = (
            "The merchant submits the order and fulfilment records below as "
            "evidence that the goods supplied conformed to their description at "
            "the point of sale."
        )

    return f"{rule} {specific}"


def render_template(dispute: DisputeEvent, bundle: EvidenceBundle) -> RebuttalDraft:
    """Produce a valid, deterministic rebuttal draft with no LLM involvement.

    Always succeeds.  Cites only artifacts present in the bundle, by
    construction, because the citation list *is* the bundle's artifact index.

    Args:
        dispute: The chargeback being rebutted.
        bundle: The evidence held for it.

    Returns:
        A :class:`RebuttalDraft` that will pass
        :func:`sentinel.llm.validators.validate_draft` for this bundle.
    """
    return RebuttalDraft(
        summary=_summary(dispute, bundle),
        evidence_narrative=_evidence_narrative(dispute, bundle),
        scheme_argument=_scheme_argument(dispute, bundle),
        cited_artifacts=artifact_index(bundle),
    )
