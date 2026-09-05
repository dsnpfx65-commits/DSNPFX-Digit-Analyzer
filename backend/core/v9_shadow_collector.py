"""DSNPFX V9 prospective research collectors.

The production scanner historically allowed only one global pending prediction.
This wrapper keeps production publication unchanged while recording one
non-trading next-tick ensemble SHADOW candidate per eligible Volatility market.

Independent strategy audits are isolated from adaptive production model memory.
They record HOT1000 MATCH, COLD200/500/1000 MATCH, COLD20 DIFFERS candidates,
Scribd MATCH rule candidates, and per-model adaptive forward candidates before
the resolving tick so actual next-tick performance can be compared honestly.
"""

from __future__ import annotations

import asyncio

from backend.core.adaptive_forward_ensemble import get_adaptive_forward_ensemble
from backend.core.cold20_forward_audit import get_cold20_forward_audit
from backend.core.filtered_strategy_collector import record_filtered_cold1000
from backend.core.market_family import attach_family_metadata
from backend.core.proposal_quote_service import (
    get_cached_differ_quote,
    get_cached_match_quote,
)
from backend.core.scribd_match_collector import record_scribd_match
from backend.core.strategy_forward_audit import get_strategy_forward_audit


_ORIGINAL_SCAN_LOOP = None


def _install_research_resolver(learning) -> None:
    """Resolve all isolated research audits from the same accepted next tick."""
    if getattr(learning, "_DSNPFX_RESEARCH_RESOLVER_INSTALLED", False):
        return

    original_resolve = learning.resolve
    cold20_audit = get_cold20_forward_audit()
    strategy_audit = get_strategy_forward_audit()
    adaptive_audit = get_adaptive_forward_ensemble()

    def resolve_with_research(
        symbol: str,
        actual: int,
        tick_epoch: int,
        tick_quote,
    ):
        # These isolated research tables never alter production publication or
        # adaptive production model memory.
        cold20_audit.resolve(
            symbol,
            actual,
            tick_epoch=tick_epoch,
            tick_quote=tick_quote,
        )
        strategy_audit.resolve(
            symbol,
            actual,
            tick_epoch=tick_epoch,
            tick_quote=tick_quote,
        )
        adaptive_audit.resolve(
            symbol,
            actual,
            tick_epoch=tick_epoch,
            tick_quote=tick_quote,
        )
        return original_resolve(
            symbol,
            actual,
            tick_epoch=tick_epoch,
            tick_quote=tick_quote,
        )

    learning.resolve = resolve_with_research
    learning._DSNPFX_RESEARCH_RESOLVER_INSTALLED = True


def install(base_module):
    global _ORIGINAL_SCAN_LOOP

    if getattr(base_module, "_DSNPFX_V9_SHADOW_INSTALLED", False):
        return

    _ORIGINAL_SCAN_LOOP = base_module._scan_loop

    async def wrapped_scan_loop(
        ai,
        learning,
        latest_ticks,
        quality_gate,
        accuracy_gate,
        worker_executor,
        generation,
    ):
        _install_research_resolver(learning)

        production_task = asyncio.create_task(
            _ORIGINAL_SCAN_LOOP(
                ai,
                learning,
                latest_ticks,
                quality_gate,
                accuracy_gate,
                worker_executor,
                generation,
            ),
            name=f"dsnpfx-production-scan-{generation}",
        )

        shadow_task = asyncio.create_task(
            _shadow_learning_loop(
                base_module,
                ai,
                learning,
                latest_ticks,
                quality_gate,
                worker_executor,
                generation,
            ),
            name=f"dsnpfx-v9-shadow-{generation}",
        )

        done, pending = await asyncio.wait(
            {production_task, shadow_task},
            return_when=asyncio.FIRST_EXCEPTION,
        )

        for task in pending:
            task.cancel()

        await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            if task.cancelled():
                continue
            exception = task.exception()
            if exception is not None:
                raise exception

    base_module._scan_loop = wrapped_scan_loop
    base_module._DSNPFX_V9_SHADOW_INSTALLED = True


def _ready_digit(report: dict) -> int | None:
    if str(report.get("status", "")).upper() != "READY":
        return None
    candidate = report.get("candidate")
    try:
        candidate = int(candidate)
    except (TypeError, ValueError):
        return None
    return candidate if 0 <= candidate <= 9 else None


def _record_cold20_candidate(result: dict, source_tick: dict) -> bool:
    metadata = result.get("model_metadata") or {}
    cold20 = metadata.get("cold_20_differs") or {}
    barrier = _ready_digit(cold20)
    if barrier is None:
        return False

    symbol = result.get("symbol")
    proposal_quote = get_cached_differ_quote(symbol, barrier)

    old_saved = get_cold20_forward_audit().create_prediction(
        symbol=symbol,
        barrier=barrier,
        source_epoch=source_tick["epoch"],
        source_quote=source_tick["quote"],
        cold_frequency_pct=cold20.get("cold_frequency_pct"),
        historical_differ_rate_pct=cold20.get("historical_differ_rate_pct"),
        proposal_quote=proposal_quote,
    )

    general_saved = get_strategy_forward_audit().create_prediction(
        symbol=symbol,
        strategy="COLD_20_DIFFERS",
        barrier=barrier,
        source_epoch=source_tick["epoch"],
        source_quote=source_tick["quote"],
        historical_rate_pct=cold20.get("historical_differ_rate_pct"),
        proposal_quote=proposal_quote,
    )
    return old_saved or general_saved


def _record_match_strategy(
    *,
    symbol: str,
    strategy: str,
    report: dict,
    source_tick: dict,
    historical_rate_pct=None,
) -> bool:
    barrier = _ready_digit(report)
    if barrier is None:
        return False

    return get_strategy_forward_audit().create_prediction(
        symbol=symbol,
        strategy=strategy,
        barrier=barrier,
        source_epoch=source_tick["epoch"],
        source_quote=source_tick["quote"],
        historical_rate_pct=(
            historical_rate_pct
            if historical_rate_pct is not None
            else report.get("frequency_pct")
        ),
        proposal_quote=get_cached_match_quote(symbol, barrier),
    )


def _record_independent_strategies(ai, result: dict, source_tick: dict) -> None:
    metadata = result.get("model_metadata") or {}
    symbol = result.get("symbol")
    if not symbol:
        return

    hot = metadata.get("hot_1000_continuation") or {}
    _record_match_strategy(
        symbol=symbol,
        strategy="HOT_1000_MATCH",
        report=hot,
        source_tick=source_tick,
        historical_rate_pct=hot.get("frequency_pct"),
    )

    cold = metadata.get("cold_reversion") or {}
    windows = cold.get("windows") or {}
    for window in (200, 500, 1000):
        report = windows.get(window) or windows.get(str(window)) or {}
        _record_match_strategy(
            symbol=symbol,
            strategy=f"COLD_{window}_MATCH",
            report=report,
            source_tick=source_tick,
            historical_rate_pct=report.get("frequency_pct"),
        )

    _record_cold20_candidate(result, source_tick)
    record_filtered_cold1000(result, source_tick)

    # The Scribd hypothesis needs actual digit history to reproduce its
    # percentage, trend/stability, and cursor rules. Reuse the live market
    # engine's bounded history instead of maintaining a second tick buffer.
    record_scribd_match(
        symbol=symbol,
        digits=ai.market_engine.history(symbol),
        source_tick=source_tick,
    )

    # Record every available research model independently before the next tick.
    # This audit remains isolated from production until its statistical gates
    # prove an edge over the 10% exact-digit baseline.
    get_adaptive_forward_ensemble().create_from_result(result, source_tick)


async def _shadow_learning_loop(
    base,
    ai,
    learning,
    latest_ticks,
    quality_gate,
    worker_executor,
    generation,
):
    while True:
        await asyncio.sleep(max(2.0, float(base.SCAN_INTERVAL)))

        if not base._generation_is_current(generation):
            return

        results = await base._run_blocking(
            worker_executor,
            ai.scan,
        )

        if not base._generation_is_current(generation):
            return

        if not results:
            continue

        attach_family_metadata(results)
        await base._run_blocking(
            worker_executor,
            base._attach_quality,
            results,
            quality_gate,
        )

        for result in results:
            if not base._generation_is_current(generation):
                return

            symbol = result.get("symbol")
            source_tick = latest_ticks.get(symbol)

            if (
                not symbol
                or symbol not in base.VOLATILITY_SYMBOLS
                or source_tick is None
                or result.get("status") != "LIVE"
            ):
                continue

            _record_independent_strategies(ai, result, source_tick)

            candidate = result.get("candidate")
            if candidate is None:
                continue

            market_quality = str(result.get("market_quality") or "UNKNOWN")
            if market_quality not in {"LOW_SAMPLE", "TEN_DIGIT"}:
                continue

            if learning.has_pending(symbol):
                continue

            model_predictions = dict(result.get("model_predictions") or {})
            model_weights = dict(result.get("model_weights") or {})
            active_models = sum(
                1
                for model, prediction in model_predictions.items()
                if prediction is not None
                and float(model_weights.get(model, 0.0) or 0.0) > 0.0
            )

            if active_models < 2:
                continue

            record = {
                "symbol": symbol,
                "prediction": None,
                "candidate": candidate,
                "confidence": result.get("confidence"),
                "edge": result.get("edge"),
                "edge_grade": result.get("edge_grade"),
                "regime": result.get("regime"),
                "model_predictions": model_predictions,
                "model_weights": model_weights,
                "edge_components": result.get("edge_components", {}),
                "model_statistics": result.get("model_statistics", {}),
                "regime_confidence": result.get("regime_confidence"),
                "stability_score": result.get("stability_score"),
                "confidence_margin": result.get("confidence_margin"),
                "market_qualified": False,
                "statistically_above_baseline": False,
                "recent_deterioration": False,
                "evidence_scope": "V9_PROSPECTIVE_SHADOW",
                "premium": False,
                "source_epoch": source_tick["epoch"],
                "source_quote": source_tick["quote"],
            }

            saved = learning.create_prediction(record)
            if not saved:
                continue

            learning.tag_pending_prediction(
                symbol,
                selection_mode="SHADOW",
                market_family=result.get("market_family", "UNKNOWN"),
                market_quality=market_quality,
            )
