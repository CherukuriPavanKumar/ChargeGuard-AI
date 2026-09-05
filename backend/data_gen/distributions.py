"""Marginal and conditional distributions for the synthetic corpus.

Every number in this file is a modelling assumption, stated in the open so a
reader can disagree with it.  The proportions are calibrated to Indian D2C
e-commerce chargeback patterns: heavy non-receipt and card-absent fraud, a
lognormal ticket distribution with a median around INR 2 400, and near-universal
3-D Secure enrolment driven by the RBI additional-factor-authentication mandate.

Nothing here is fitted to real data -- there is no real data.  These are priors
chosen to make the *decision problem* realistic: a long-tailed amount
distribution so the per-dispute threshold actually varies over two orders of
magnitude, and reason-code mix weighted toward codes where evidence quality
genuinely swings the outcome.
"""

from __future__ import annotations

import numpy as np

from sentinel.schemas.dispute import CardNetwork, ReasonCode
from sentinel.schemas.evidence import Carrier, ThreeDSStatus

# --------------------------------------------------------------------------- #
# Reason codes                                                                #
# --------------------------------------------------------------------------- #

#: Reason-code mix. Non-receipt dominates Indian D2C because of address quality
#: and last-mile handover disputes; card-absent fraud denial is the second
#: cluster and is where friendly fraud concentrates.
REASON_CODE_WEIGHTS: dict[ReasonCode, float] = {
    ReasonCode.VISA_13_1: 0.28,  # merchandise not received
    ReasonCode.VISA_10_4: 0.22,  # fraud, card-absent
    ReasonCode.VISA_13_3: 0.16,  # not as described
    ReasonCode.MC_4853: 0.14,  # cardholder dispute
    ReasonCode.MC_4837: 0.12,  # no cardholder authorisation
    ReasonCode.VISA_13_6: 0.08,  # credit not processed
}

#: Network implied by the reason code. Visa codes are Visa; Mastercard codes are
#: Mastercard; a slice of Mastercard-coded volume is RuPay, which maps disputes
#: onto Mastercard-equivalent codes domestically.
RUPAY_SHARE_OF_MC_CODES: float = 0.18


# --------------------------------------------------------------------------- #
# Amounts                                                                     #
# --------------------------------------------------------------------------- #

#: Target median of the *realised* corpus, in INR.
AMOUNT_MEDIAN_TARGET: float = 2400.0

#: Dispersion. sigma=1.05 puts the 99th percentile near INR 27 000 and the
#: 99.9th near INR 61 000 -- a genuine long tail, which is what makes the
#: per-dispute threshold interesting rather than decorative.
AMOUNT_SIGMA: float = 1.05

#: Hard clip. The floor sits below the representment cost so that
#: ``amount_below_cost_gate`` has real work to do; the ceiling matches the
#: spec's stated tail.
AMOUNT_MIN: float = 149.0
AMOUNT_MAX: float = 80_000.0

#: Reason-code-conditional amount multipliers. Electronics and high-ticket goods
#: cluster in fraud denial; subscription and small-goods complaints cluster in
#: credit-not-processed.
AMOUNT_MULTIPLIER: dict[ReasonCode, float] = {
    ReasonCode.VISA_10_4: 1.55,
    ReasonCode.MC_4837: 1.45,
    ReasonCode.VISA_13_1: 1.00,
    ReasonCode.MC_4853: 0.95,
    ReasonCode.VISA_13_3: 0.90,
    ReasonCode.VISA_13_6: 0.55,
}


def _multiplier_geometric_mean() -> float:
    """Weighted geometric mean of the reason-code amount multipliers.

    The multipliers shift the realised median away from ``exp(mu)``.  Because
    the mixture is lognormal in each component, the aggregate median moves by
    the *geometric* mean of the multipliers weighted by reason-code share.
    Dividing it out makes the realised corpus median land on
    :data:`AMOUNT_MEDIAN_TARGET` regardless of how the mix or the multipliers
    are later retuned -- a hand-tuned constant would silently go stale.
    """
    total = sum(REASON_CODE_WEIGHTS.values())
    log_mean = sum(
        (weight / total) * float(np.log(AMOUNT_MULTIPLIER[code]))
        for code, weight in REASON_CODE_WEIGHTS.items()
    )
    return float(np.exp(log_mean))


#: mu of the underlying lognormal, back-solved so the *post-multiplier* median
#: equals :data:`AMOUNT_MEDIAN_TARGET`.
AMOUNT_MU: float = float(
    np.log(AMOUNT_MEDIAN_TARGET / _multiplier_geometric_mean())
)


def sample_amounts(
    rng: np.random.Generator, reason_codes: list[ReasonCode]
) -> np.ndarray:
    """Draw disputed amounts in INR, conditional on reason code.

    Returns a float array rounded to two decimals and clipped to
    ``[AMOUNT_MIN, AMOUNT_MAX]``.
    """
    n = len(reason_codes)
    base = rng.lognormal(mean=AMOUNT_MU, sigma=AMOUNT_SIGMA, size=n)
    multipliers = np.array(
        [AMOUNT_MULTIPLIER[code] for code in reason_codes], dtype=np.float64
    )
    amounts = np.clip(base * multipliers, AMOUNT_MIN, AMOUNT_MAX)
    return np.round(amounts, 2)


def sample_reason_codes(rng: np.random.Generator, n: int) -> list[ReasonCode]:
    """Draw ``n`` reason codes from :data:`REASON_CODE_WEIGHTS`."""
    codes = list(REASON_CODE_WEIGHTS.keys())
    weights = np.array(list(REASON_CODE_WEIGHTS.values()), dtype=np.float64)
    weights = weights / weights.sum()
    idx = rng.choice(len(codes), size=n, p=weights)
    return [codes[i] for i in idx]


def network_for_reason(
    rng: np.random.Generator, reason_code: ReasonCode
) -> CardNetwork:
    """Map a reason code to the network that would have raised it."""
    if reason_code.value.startswith("VISA"):
        return CardNetwork.VISA
    if rng.random() < RUPAY_SHARE_OF_MC_CODES:
        return CardNetwork.RUPAY
    return CardNetwork.MASTERCARD


# --------------------------------------------------------------------------- #
# 3-D Secure, conditional on amount                                           #
# --------------------------------------------------------------------------- #

#: Amount above which step-up authentication is near-universal. India's AFA
#: mandate means low-value transactions may ride an e-mandate exemption, while
#: high-value ones are almost always challenged.
THREE_DS_PIVOT_INR: float = 5_000.0


def three_ds_probabilities(amount_inr: float) -> dict[ThreeDSStatus, float]:
    """Return the 3-D Secure outcome distribution for a given amount.

    Authentication rate rises with amount: a INR 500 order often rides an
    exemption and lands ``NOT_ENROLLED``, while a INR 30 000 order is challenged
    and lands ``AUTHENTICATED`` or ``FAILED``.

    This conditioning matters because ``three_ds_status`` is the hinge of
    ``fraud_without_liability_shift_gate``.  Making it independent of amount
    would decouple the gate from the economics and make its activation pattern
    uninformative.
    """
    # Logistic ramp on log-amount, centred at the pivot.
    x = float(np.log(max(amount_inr, 1.0)) - np.log(THREE_DS_PIVOT_INR))
    challenged = 1.0 / (1.0 + np.exp(-1.35 * x))
    challenged = 0.32 + 0.62 * challenged  # floor 32%, ceiling 94%

    # Of challenged transactions, most authenticate; a minority abandon or fail.
    authenticated = challenged * 0.80
    attempted = challenged * 0.12
    failed = challenged * 0.08
    not_enrolled = 1.0 - challenged

    return {
        ThreeDSStatus.AUTHENTICATED: authenticated,
        ThreeDSStatus.ATTEMPTED: attempted,
        ThreeDSStatus.FAILED: failed,
        ThreeDSStatus.NOT_ENROLLED: not_enrolled,
    }


def sample_three_ds(rng: np.random.Generator, amount_inr: float) -> ThreeDSStatus:
    """Draw one 3-D Secure status conditional on the amount."""
    probs = three_ds_probabilities(amount_inr)
    statuses = list(probs.keys())
    weights = np.array(list(probs.values()), dtype=np.float64)
    weights = weights / weights.sum()
    return statuses[int(rng.choice(len(statuses), p=weights))]


# --------------------------------------------------------------------------- #
# Carriers and scan trails                                                    #
# --------------------------------------------------------------------------- #

#: Last-mile share. Roughly reflects Indian D2C carrier allocation.
CARRIER_WEIGHTS: dict[Carrier, float] = {
    Carrier.DELHIVERY: 0.34,
    Carrier.EKART: 0.26,
    Carrier.BLUEDART: 0.22,
    Carrier.XPRESSBEES: 0.18,
}

#: Per-carrier scan-count distributions as ``(lambda, floor, ceiling)``.
#: Bluedart's express network produces the densest scan trail; Ekart's
#: marketplace integration the sparsest. Scan density is corroborating evidence,
#: so this variation gives the model a genuine carrier-conditional signal.
CARRIER_SCAN_PARAMS: dict[Carrier, tuple[float, int, int]] = {
    Carrier.BLUEDART: (7.2, 3, 14),
    Carrier.DELHIVERY: (5.6, 2, 12),
    Carrier.XPRESSBEES: (4.8, 2, 11),
    Carrier.EKART: (4.1, 1, 10),
    Carrier.UNKNOWN: (3.0, 0, 8),
}

#: Per-carrier baseline print quality, driving OCR confidence before damage.
#: Bluedart prints thermal labels at high contrast; Ekart's handheld slips are
#: the worst. This is what makes the OCR confidence distribution multimodal
#: rather than a single blob.
CARRIER_PRINT_QUALITY: dict[Carrier, float] = {
    Carrier.BLUEDART: 0.88,
    Carrier.DELHIVERY: 0.81,
    Carrier.XPRESSBEES: 0.76,
    Carrier.EKART: 0.70,
    Carrier.UNKNOWN: 0.60,
}


def sample_carrier(rng: np.random.Generator) -> Carrier:
    """Draw a last-mile carrier."""
    carriers = list(CARRIER_WEIGHTS.keys())
    weights = np.array(list(CARRIER_WEIGHTS.values()), dtype=np.float64)
    weights = weights / weights.sum()
    return carriers[int(rng.choice(len(carriers), p=weights))]


def sample_scan_count(rng: np.random.Generator, carrier: Carrier) -> int:
    """Draw a scan count from the carrier's Poisson trail, clipped to its range."""
    lam, floor, ceiling = CARRIER_SCAN_PARAMS[carrier]
    return int(np.clip(rng.poisson(lam), floor, ceiling))


# --------------------------------------------------------------------------- #
# Timing                                                                      #
# --------------------------------------------------------------------------- #

#: Representment window width in hours, uniform over 7 to 30 days. Schemes vary
#: by code and region; this brackets the realistic range.
WINDOW_HOURS_RANGE: tuple[float, float] = (7 * 24.0, 30 * 24.0)

#: Hours remaining at the corpus anchor for a live dispute.
LIVE_HOURS_REMAINING_RANGE: tuple[float, float] = (2.0, 600.0)

#: Hours already elapsed past the deadline for an expired dispute.
EXPIRED_HOURS_OVERDUE_RANGE: tuple[float, float] = (1.0, 240.0)

#: Days from order placement to the chargeback being raised.
DISPUTE_LAG_DAYS_RANGE: tuple[float, float] = (10.0, 120.0)

#: Delivery lag in hours from order placement to the delivery scan.
DELIVERY_LAG_HOURS_RANGE: tuple[float, float] = (18.0, 240.0)

#: Account age in days at order time. Bimodal: established buyers versus
#: accounts minted immediately before the order, which is a friendly-fraud tell.
ACCOUNT_AGE_ESTABLISHED_RANGE: tuple[float, float] = (45.0, 1400.0)
ACCOUNT_AGE_FRESH_RANGE: tuple[float, float] = (0.02, 5.0)

#: Probability an account is "fresh", conditional on friendly fraud.
FRESH_ACCOUNT_PROB_FRAUD: float = 0.42
FRESH_ACCOUNT_PROB_GENUINE: float = 0.07

#: Minutes from session login to order placement. Long tail for browsing
#: sessions; a spike near zero for scripted checkout.
LOGIN_TO_ORDER_SCRIPTED_RANGE: tuple[float, float] = (0.05, 1.5)
LOGIN_TO_ORDER_HUMAN_RANGE: tuple[float, float] = (2.0, 90.0)
SCRIPTED_CHECKOUT_PROB_FRAUD: float = 0.30
SCRIPTED_CHECKOUT_PROB_GENUINE: float = 0.04


# --------------------------------------------------------------------------- #
# Geography                                                                   #
# --------------------------------------------------------------------------- #

#: Major Indian metro coordinates for domestic IP geolocation, with the city and
#: state strings used to synthesise matching postal addresses.
INDIAN_CITIES: tuple[tuple[str, str, float, float, str], ...] = (
    ("Mumbai", "Maharashtra", 19.0760, 72.8777, "400"),
    ("Delhi", "Delhi", 28.6139, 77.2090, "110"),
    ("Bengaluru", "Karnataka", 12.9716, 77.5946, "560"),
    ("Hyderabad", "Telangana", 17.3850, 78.4867, "500"),
    ("Chennai", "Tamil Nadu", 13.0827, 80.2707, "600"),
    ("Kolkata", "West Bengal", 22.5726, 88.3639, "700"),
    ("Pune", "Maharashtra", 18.5204, 73.8567, "411"),
    ("Ahmedabad", "Gujarat", 23.0225, 72.5714, "380"),
    ("Jaipur", "Rajasthan", 26.9124, 75.7873, "302"),
    ("Lucknow", "Uttar Pradesh", 26.8467, 80.9462, "226"),
    ("Kochi", "Kerala", 9.9312, 76.2673, "682"),
    ("Chandigarh", "Punjab", 30.7333, 76.7794, "160"),
)

#: Offshore coordinates used when a session originates outside India. Chosen
#: from jurisdictions that commonly appear in card-not-present abuse traffic.
OFFSHORE_COORDS: tuple[tuple[float, float], ...] = (
    (1.3521, 103.8198),  # Singapore
    (25.2048, 55.2708),  # Dubai
    (51.5074, -0.1278),  # London
    (40.7128, -74.0060),  # New York
    (-33.8688, 151.2093),  # Sydney
    (55.7558, 37.6173),  # Moscow
    (6.5244, 3.3792),  # Lagos
)

#: Probability the checkout IP is offshore, conditional on friendly fraud.
OFFSHORE_PROB_FRAUD: float = 0.19
OFFSHORE_PROB_GENUINE: float = 0.03


def sample_city(rng: np.random.Generator) -> tuple[str, str, float, float, str]:
    """Draw one Indian metro record."""
    return INDIAN_CITIES[int(rng.integers(0, len(INDIAN_CITIES)))]


def jitter_coords(
    rng: np.random.Generator, lat: float, lon: float, spread_deg: float = 0.16
) -> tuple[float, float]:
    """Add metro-scale jitter to a city centroid, mimicking IP geolocation error."""
    return (
        float(lat + rng.normal(0.0, spread_deg)),
        float(lon + rng.normal(0.0, spread_deg)),
    )


# --------------------------------------------------------------------------- #
# Identity vocabulary                                                         #
# --------------------------------------------------------------------------- #

FIRST_NAMES: tuple[str, ...] = (
    "Aarav", "Vivaan", "Aditya", "Rohan", "Karthik", "Ishaan", "Rajesh",
    "Suresh", "Ananya", "Diya", "Priya", "Meera", "Kavya", "Sneha",
    "Arjun", "Nikhil", "Farhan", "Zoya", "Riya", "Tanvi", "Manish",
    "Deepak", "Neha", "Pooja", "Rahul", "Sanjay", "Aisha", "Imran",
)

LAST_NAMES: tuple[str, ...] = (
    "Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Singh", "Gupta",
    "Mehta", "Joshi", "Kulkarni", "Chatterjee", "Banerjee", "Rao", "Khan",
    "Desai", "Malhotra", "Bose", "Pillai", "Chauhan", "Kapoor", "Menon",
)

STREET_NAMES: tuple[str, ...] = (
    "MG Road", "Linking Road", "Brigade Road", "Park Street", "Anna Salai",
    "SV Road", "Ring Road", "Station Road", "Church Street", "Residency Road",
    "Nehru Nagar", "Gandhi Marg", "Sardar Patel Marg", "Hill Road",
)

BUILDING_NAMES: tuple[str, ...] = (
    "Sunrise Apartments", "Green Meadows", "Silver Oak", "Palm Grove",
    "Lake View Residency", "Orchid Towers", "Maple Heights", "Sai Krupa",
    "Shanti Niketan", "Crystal Court", "Rose Villa", "Emerald Enclave",
)

ITEM_CATALOGUE: tuple[tuple[str, float], ...] = (
    ("Wireless Earbuds (ANC)", 4499.0),
    ("Cotton Kurta Set", 1899.0),
    ("Stainless Steel Cookware Set", 3299.0),
    ("Smartphone Case + Screen Guard", 649.0),
    ("Running Shoes", 2799.0),
    ("Bluetooth Speaker", 2199.0),
    ("Ayurvedic Skincare Kit", 1249.0),
    ("Mechanical Keyboard", 5899.0),
    ("Smart Watch Series 6", 12499.0),
    ("4K Action Camera", 18999.0),
    ("Laptop Backpack", 1699.0),
    ("Organic Green Tea 500g", 549.0),
    ("LED Monitor 27 inch", 16499.0),
    ("Gaming Mouse", 2399.0),
    ("Yoga Mat 6mm", 899.0),
    ("Air Fryer 4L", 7499.0),
    ("Noise Cancelling Headphones", 9999.0),
    ("Monthly Subscription Renewal", 449.0),
)

USER_AGENTS_MOBILE: tuple[str, ...] = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; RMX3771) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0 Mobile Safari/537.36",
)

USER_AGENTS_DESKTOP: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
)

#: Share of Indian D2C checkout traffic on mobile.
MOBILE_SHARE: float = 0.72
