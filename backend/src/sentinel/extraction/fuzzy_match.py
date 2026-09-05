"""Fuzzy string agreement between evidence sources.

Two artifacts that should describe the same person and place rarely do so
identically.  A courier writes "RAJESH K." where the order says "Rajesh Kumar
Sharma".  The POD address reads "Flat 402, Sunrise Apts, Andheri E, Mumbai
400069" where the OMS holds "402 Sunrise Apartments, Andheri East, Mumbai,
Maharashtra 400069".  Exact matching would score both at zero and throw away the
strongest evidence in the bundle.

``token_set_ratio`` is the right primitive here because it is invariant to word
order and to one side carrying extra tokens -- exactly the two ways addresses
and names differ in practice.

This module is **pure**: no I/O, no clock, no randomness.  It is imported by
``sentinel.features.builder``, which is bound by INVARIANT 2, so it must remain
so.  ``rapidfuzz`` is a pure C-extension computation with no side effects.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

#: Tokens that carry no discriminative signal in Indian postal addresses. Removed
#: before comparison so that two addresses are not credited for both saying "road".
_ADDRESS_STOPWORDS: frozenset[str] = frozenset(
    {
        "flat",
        "apt",
        "apts",
        "apartment",
        "apartments",
        "block",
        "building",
        "bldg",
        "floor",
        "near",
        "opp",
        "opposite",
        "road",
        "rd",
        "street",
        "st",
        "lane",
        "cross",
        "main",
        "sector",
        "phase",
        "no",
        "number",
        "india",
    }
)

#: Honorifics and initials-noise stripped before comparing personal names.
_NAME_STOPWORDS: frozenset[str] = frozenset(
    {"mr", "mrs", "ms", "dr", "shri", "smt", "sri", "kum", "prof"}
)

#: Common abbreviation expansions, applied before tokenisation so that
#: "Andheri E" and "Andheri East" agree.
_ADDRESS_EXPANSIONS: tuple[tuple[str, str], ...] = (
    (r"\be\b", "east"),
    (r"\bw\b", "west"),
    (r"\bn\b", "north"),
    (r"\bs\b", "south"),
    (r"\bnr\b", "near"),
    (r"\bmah\b", "maharashtra"),
    (r"\bknt\b", "karnataka"),
    (r"\bdl\b", "delhi"),
    (r"\btn\b", "tamil nadu"),
)

_NON_ALNUM = re.compile(r"[^a-z0-9\s]")
_WHITESPACE = re.compile(r"\s+")


def _normalise(text: str, stopwords: frozenset[str]) -> str:
    """Lowercase, strip punctuation, drop stopwords, collapse whitespace."""
    lowered = _NON_ALNUM.sub(" ", text.lower())
    collapsed = _WHITESPACE.sub(" ", lowered).strip()
    if not collapsed:
        return ""
    kept = [tok for tok in collapsed.split(" ") if tok not in stopwords]
    return " ".join(kept)


def _expand_address(text: str) -> str:
    """Apply directional and state abbreviation expansions."""
    out = text
    for pattern, replacement in _ADDRESS_EXPANSIONS:
        out = re.sub(pattern, replacement, out)
    return out


def name_similarity(pod_recipient: str, order_customer: str) -> float:
    """Return agreement in [0, 1] between the POD signatory and the buyer.

    Uses ``token_set_ratio``, which scores "RAJESH K" against "Rajesh Kumar
    Sharma" highly because the shared token set dominates: the courier's slip is
    almost always a truncation of the full name rather than a different name.

    Returns ``0.0`` when either side is empty, which is the correct reading --
    an unparsed recipient field is no evidence, not disagreement.
    """
    left = _normalise(pod_recipient, _NAME_STOPWORDS)
    right = _normalise(order_customer, _NAME_STOPWORDS)
    if not left or not right:
        return 0.0
    return float(fuzz.token_set_ratio(left, right)) / 100.0


def address_similarity(pod_address: str, order_address: str) -> float:
    """Return agreement in [0, 1] between the delivery and shipping addresses.

    Stopword removal and abbreviation expansion run first so that formatting
    conventions do not depress the score.  The postal code, when present on both
    sides, is the highest-signal token and survives normalisation intact.

    Returns ``0.0`` when either side is empty.
    """
    left = _expand_address(_normalise(pod_address, _ADDRESS_STOPWORDS))
    right = _expand_address(_normalise(order_address, _ADDRESS_STOPWORDS))
    if not left or not right:
        return 0.0
    return float(fuzz.token_set_ratio(left, right)) / 100.0


def pincode_matches(left: str, right: str) -> bool:
    """True when both strings contain the same six-digit Indian postal code.

    A hard corroborating check that survives heavy OCR damage to the rest of the
    address block: digits are more robust to blur than letters.
    """
    left_codes = set(re.findall(r"\b[1-9][0-9]{5}\b", left))
    right_codes = set(re.findall(r"\b[1-9][0-9]{5}\b", right))
    if not left_codes or not right_codes:
        return False
    return bool(left_codes & right_codes)
