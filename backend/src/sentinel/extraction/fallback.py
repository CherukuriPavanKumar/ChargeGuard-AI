"""The single degradation path.

INVARIANT 6: every failure in the evidence layer routes through
:func:`degrade`.  There is exactly one function in the codebase that produces a
post-failure bundle, so the question "what does the system believe when
something broke?" has exactly one answer to audit.

Degradation is *pessimistic*, not neutral
-----------------------------------------
When extraction fails we do not guess. We downgrade every unverifiable claim and
let the policy layer decide with less evidence.  The economics make this safe
rather than costly: a degraded bundle produces a lower ``p_win``, and a lower
``p_win`` only flips the decision when the dispute was already marginal.  On a
INR 40 000 dispute the threshold is 0.011, so even a heavily degraded bundle
still clears it -- degradation costs us the small cases and preserves the large
ones, which is precisely the right ordering given the FN/FP asymmetry.

What is *not* degraded
----------------------
Order records and session telemetry come from the merchant's own systems, not
from a lossy extraction step.  Degrading them because OCR failed would discard
sound evidence over an unrelated fault.  Only the POD -- the one artifact that
passes through a fallible reader -- is downgraded, and ``ABSENT`` is preserved
as ``ABSENT`` rather than being promoted to ``UNVERIFIED``: a missing document
does not become a present-but-unreadable one because something else crashed.
"""

from __future__ import annotations

import logging

from sentinel.extraction import ocr
from sentinel.schemas.evidence import EvidenceBundle, ExtractionStatus

logger = logging.getLogger(__name__)


def degrade(bundle: EvidenceBundle, reason: str) -> EvidenceBundle:
    """Return a valid but pessimistic copy of ``bundle``.

    Args:
        bundle: The bundle as assembled before the failure.
        reason: Human-readable cause, recorded on the result and logged.

    Returns:
        A new frozen bundle with the proof of delivery downgraded to
        ``UNVERIFIED`` (unless it was ``ABSENT``, which is preserved), and
        ``degraded=True`` carrying ``reason``.

    The returned bundle is always schema-valid: downstream code needs no
    special-casing, and the feature builder produces a normal vector from it.
    """
    logger.warning("degrading evidence bundle: %s", reason)

    if bundle.pod.extraction_status is ExtractionStatus.ABSENT:
        # No document existed before the failure and none exists now. Promoting
        # this to UNVERIFIED would wrongly suppress no_pod_on_non_receipt_gate.
        degraded_pod = bundle.pod
    else:
        degraded_pod = ocr.unverified(reason)

    return EvidenceBundle(
        pod=degraded_pod,
        order=bundle.order,
        session=bundle.session,
        prior_dispute_count=bundle.prior_dispute_count,
        refund_requested=bundle.refund_requested,
        merchant_comms_count=bundle.merchant_comms_count,
        degraded=True,
        degradation_reason=reason,
    )


def degrade_if(
    bundle: EvidenceBundle, condition: bool, reason: str
) -> EvidenceBundle:
    """Conditionally degrade, returning ``bundle`` untouched when healthy.

    Keeps call sites free of ``if`` statements around the degradation decision,
    so that the healthy and degraded paths are visibly the same code path.
    """
    if not condition:
        return bundle
    return degrade(bundle, reason)


def is_degraded(bundle: EvidenceBundle) -> bool:
    """True when this bundle is the product of a failure path."""
    return bundle.degraded
