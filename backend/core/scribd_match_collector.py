"""Prospective audit collector for the research-only Scribd MATCH rules.

This collector is deliberately fail-closed: research telemetry must never be able
to interrupt the live scanner. Any collector error returns no saved hypotheses
and leaves production prediction/publication untouched.
"""

from __future__ import annotations

from backend.core.proposal_quote_service import get_cached_match_quote
from backend.core.scribd_match_strategy import analyze_scribd_match
from backend.core.strategy_forward_audit import STRATEGIES, get_strategy_forward_audit


for digit in range(10):
    STRATEGIES.setdefault(
        f"SCRIBD_MATCH_{digit}",
        {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
    )


def record_scribd_match(*, symbol: str, digits, source_tick: dict) -> list[str]:
    try:
        analysis = analyze_scribd_match(digits)
        saved: list[str] = []

        for target in analysis.get("ready_targets", []):
            strategy = f"SCRIBD_MATCH_{target}"
            historical_rate = (analysis.get("percentages") or {}).get(target)
            created = get_strategy_forward_audit().create_prediction(
                symbol=symbol,
                strategy=strategy,
                barrier=target,
                source_epoch=source_tick["epoch"],
                source_quote=source_tick["quote"],
                historical_rate_pct=historical_rate,
                proposal_quote=get_cached_match_quote(symbol, target),
            )
            if created:
                saved.append(strategy)

        return saved
    except Exception as error:
        print(f"SCRIBD MATCH RESEARCH ERROR {symbol}: {error}")
        return []
