"""V12 precision-first selector for exact next-digit publication.

The selector does not invent a new digit. It adds a context-specific validation
layer on top of the already strict adaptive forward ensemble. A candidate may
pass only when:

1. the adaptive ensemble has already verified the digit for use;
2. the currently active market condition matches a prospectively audited
   conditional row;
3. that row has independent validation evidence whose 95% Wilson lower bound
   clears its recorded live DIGITMATCH break-even; and
4. the validated conditional model currently predicts the same digit.

This intentionally trades coverage for accuracy. If evidence is absent, the
correct output is WAIT / no prediction.
"""
from __future__ import annotations

from backend.core.conditional_forward_discovery import (
    MIN_DISCOVERY,
    MIN_VALIDATION,
    _condition_profiles,
    _model_candidates,
    get_conditional_forward_discovery,
)


MIN_VALIDATION_FOR_PRECISION = max(100, int(MIN_VALIDATION))
MIN_DISCOVERY_FOR_PRECISION = max(200, int(MIN_DISCOVERY))


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def select_precision_candidate(
    result: dict,
    adaptive_decision: dict,
    *,
    rows: list[dict] | None = None,
) -> dict:
    """Return a precision-gated decision using only prospective evidence.

    ``rows`` is injectable for deterministic tests. Production reads the
    conditional discovery leaderboard for the current symbol.
    """
    symbol = str(result.get("symbol") or "")
    adaptive_candidate = adaptive_decision.get("candidate")
    if not adaptive_decision.get("verified_for_use") or adaptive_candidate is None:
        return {
            "candidate": None,
            "verified_for_use": False,
            "reason": "Adaptive forward ensemble has no verified candidate",
            "supporting_model": None,
            "condition_family": None,
            "condition_value": None,
            "validation_lower_95_pct": 0.0,
            "validation_break_even_pct": None,
            "conservative_edge_pp": 0.0,
        }

    try:
        adaptive_candidate = int(adaptive_candidate)
    except (TypeError, ValueError):
        adaptive_candidate = None
    if adaptive_candidate is None or not 0 <= adaptive_candidate <= 9:
        return {
            "candidate": None,
            "verified_for_use": False,
            "reason": "Adaptive candidate is not a valid digit",
            "supporting_model": None,
            "condition_family": None,
            "condition_value": None,
            "validation_lower_95_pct": 0.0,
            "validation_break_even_pct": None,
            "conservative_edge_pp": 0.0,
        }

    candidates = _model_candidates(result)
    active_profiles = set(_condition_profiles(result, candidates))
    adaptive_supporters = set(adaptive_decision.get("supporting_models") or [])

    if rows is None:
        rows = get_conditional_forward_discovery().leaderboard(symbol=symbol, limit=10000)

    qualified = []
    for row in rows:
        if str(row.get("symbol") or "") != symbol:
            continue
        model = str(row.get("model") or "")
        if model not in adaptive_supporters:
            continue
        if candidates.get(model) != adaptive_candidate:
            continue
        profile_key = (str(row.get("condition_family")), str(row.get("condition_value")))
        if profile_key not in active_profiles:
            continue

        discovery = row.get("discovery") or {}
        validation = row.get("validation") or {}
        avg_be = validation.get("average_break_even_pct")
        lower = _f(validation.get("lower_95_pct"))
        resolved = int(validation.get("resolved") or 0)

        if int(discovery.get("resolved") or 0) < MIN_DISCOVERY_FOR_PRECISION:
            continue
        if resolved < MIN_VALIDATION_FOR_PRECISION:
            continue
        if avg_be is None:
            continue
        avg_be = _f(avg_be, -1.0)
        if avg_be <= 0.0 or lower <= avg_be:
            continue
        if not bool(row.get("validation_economic_edge")):
            continue

        qualified.append((
            lower - avg_be,
            resolved,
            lower,
            row,
            avg_be,
        ))

    if not qualified:
        return {
            "candidate": None,
            "verified_for_use": False,
            "reason": "No active conditional validation edge confirms the adaptive digit",
            "supporting_model": None,
            "condition_family": None,
            "condition_value": None,
            "validation_lower_95_pct": 0.0,
            "validation_break_even_pct": None,
            "conservative_edge_pp": 0.0,
        }

    qualified.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    edge, resolved, lower, row, avg_be = qualified[0]
    return {
        "candidate": adaptive_candidate,
        "verified_for_use": True,
        "reason": "Adaptive digit confirmed by active independently validated condition",
        "supporting_model": row.get("model"),
        "condition_family": row.get("condition_family"),
        "condition_value": row.get("condition_value"),
        "validation_resolved": resolved,
        "validation_lower_95_pct": round(lower, 4),
        "validation_break_even_pct": round(avg_be, 4),
        "conservative_edge_pp": round(edge, 4),
    }
