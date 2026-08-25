"""
DSNPFX Market Family Intelligence V1

Classifies Deriv synthetic symbols and applies the initial
production eligibility policy.

V1 production policy:
- Standard Volatility indices: premium eligible
- 1-second Volatility indices: shadow learning
- Jump indices: shadow learning
- Boom indices: shadow learning
- Crash indices: shadow learning
- Step indices: research only

This policy can be relaxed only after family-specific
confidence and edge calibration are validated.
"""

from __future__ import annotations

from collections import defaultdict


FAMILY_VOLATILITY = "VOLATILITY"
FAMILY_VOLATILITY_1S = "VOLATILITY_1S"
FAMILY_STEP = "STEP"
FAMILY_JUMP = "JUMP"
FAMILY_BOOM = "BOOM"
FAMILY_CRASH = "CRASH"
FAMILY_UNKNOWN = "UNKNOWN"


PREMIUM_FAMILIES = {
    FAMILY_VOLATILITY,
}

SHADOW_FAMILIES = {
    FAMILY_VOLATILITY,
    FAMILY_VOLATILITY_1S,
    FAMILY_JUMP,
    FAMILY_BOOM,
    FAMILY_CRASH,
}

RESEARCH_ONLY_FAMILIES = {
    FAMILY_STEP,
    FAMILY_UNKNOWN,
}


def classify_market_family(symbol: str) -> str:
    symbol = str(symbol or "").strip().upper()

    if not symbol:
        return FAMILY_UNKNOWN

    if symbol.startswith("1HZ"):
        return FAMILY_VOLATILITY_1S

    if symbol.startswith("R_"):
        return FAMILY_VOLATILITY

    if symbol.startswith("STPRNG"):
        return FAMILY_STEP

    if symbol.startswith("JD"):
        return FAMILY_JUMP

    if symbol.startswith("BOOM"):
        return FAMILY_BOOM

    if symbol.startswith("CRASH"):
        return FAMILY_CRASH

    return FAMILY_UNKNOWN


def premium_eligible_family(family: str) -> bool:
    return family in PREMIUM_FAMILIES


def shadow_eligible_family(family: str) -> bool:
    return family in SHADOW_FAMILIES


def research_only_family(family: str) -> bool:
    return family in RESEARCH_ONLY_FAMILIES


def attach_family_metadata(results: list[dict]) -> None:
    for result in results:
        family = classify_market_family(
            result.get("symbol")
        )

        result["market_family"] = family
        result["family_premium_eligible"] = (
            premium_eligible_family(family)
        )
        result["family_shadow_eligible"] = (
            shadow_eligible_family(family)
        )
        result["family_research_only"] = (
            research_only_family(family)
        )


def family_leaders(
    results: list[dict],
) -> dict[str, dict]:
    """
    Return the highest-edge LIVE result for each family.

    Results are expected to already be sorted by edge, but this
    function remains deterministic even when they are not.
    """

    grouped = defaultdict(list)

    for result in results:
        if result.get("status") != "LIVE":
            continue

        family = result.get(
            "market_family",
            FAMILY_UNKNOWN,
        )

        grouped[family].append(result)

    leaders = {}

    for family, family_results in grouped.items():
        leaders[family] = max(
            family_results,
            key=lambda item: float(
                item.get("edge", 0) or 0
            ),
        )

    return leaders


def select_overall_premium_leader(
    leaders: dict[str, dict],
) -> dict | None:
    """
    Select the strongest premium-approved family leader.

    Only family leaders that:
    - are premium,
    - are TEN_DIGIT,
    - belong to a premium-approved family,
    may become the overall premium opportunity.
    """

    eligible = [
        result
        for result in leaders.values()
        if result.get("premium")
        and result.get("market_quality") == "TEN_DIGIT"
        and result.get("family_premium_eligible")
    ]

    if not eligible:
        return None

    return max(
        eligible,
        key=lambda item: float(
            item.get("edge", 0) or 0
        ),
    )
