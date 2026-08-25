"""DSNPFX V9 prospective research collectors.

The production scanner historically allowed only one global pending prediction.
This wrapper keeps production publication unchanged while recording one
non-trading next-tick ensemble SHADOW candidate per eligible Volatility market.

It also maintains a completely separate COLD_20_DIFFERS audit. COLD20 records
use DIGITDIFF semantics (WIN when the next digit differs from the barrier) and
never update adaptive production model memory.
"""

from __future__ import annotations

import asyncio

from backend.core.cold20_forward_audit import get_cold20_forward_audit
from backend.core.market_family import attach_family_metadata
from backend.core.proposal_quote_service import get_cached_differ_quote


_ORIGINAL_SCAN_LOOP = None


def _install_cold20_resolver(learning) -> None:
    """Resolve the independent COLD20 audit from the same accepted next tick."""
    if getattr(learning, "_DSNPFX_COLD20_RESOLVER_INSTALLED", False):
        return

    original_resolve = learning.resolve
    audit = get_cold20_forward_audit()

    def resolve_with_cold20(
        symbol: str,
        actual: int,
        tick_epoch: int,
        tick_quote,
    ):
        # Resolve research evidence first. This does not alter the production
        # prediction table or model memory.
        audit.resolve(
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

    learning.resolve = resolve_with_cold20
    learning._DSNPFX_COLD20_RESOLVER_INSTALLED = True


def install(base_module):
    """Install the V9 scan wrapper onto volatility_web_runner once."""
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
        _install_cold20_resolver(learning)

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


def _record_cold20_candidate(result: dict, source_tick: dict) -> bool:
    """Create one strictly prospective COLD20 record for this market."""
    metadata = result.get("model_metadata") or {}
    cold20 = metadata.get("cold_20_differs") or {}
    candidate = cold20.get("candidate")

    if candidate is None or str(cold20.get("status", "")).upper() != "READY":
        return False

    try:
        barrier = int(candidate)
    except (TypeError, ValueError):
        return False
    if not 0 <= barrier <= 9:
        return False

    symbol = result.get("symbol")
    proposal_quote = get_cached_differ_quote(symbol, barrier)

    return get_cold20_forward_audit().create_prediction(
        symbol=symbol,
        barrier=barrier,
        source_epoch=source_tick["epoch"],
        source_quote=source_tick["quote"],
        cold_frequency_pct=cold20.get("cold_frequency_pct"),
        historical_differ_rate_pct=cold20.get("historical_differ_rate_pct"),
        proposal_quote=proposal_quote,
    )


async def _shadow_learning_loop(
    base,
    ai,
    learning,
    latest_ticks,
    quality_gate,
    worker_executor,
    generation,
):
    """Record prospective research candidates without weakening production."""
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

            # COLD20 is intentionally independent of the ensemble candidate,
            # active-model count, market quality, and production thresholds.
            # Its own database permits one pending next-tick record per symbol.
            _record_cold20_candidate(result, source_tick)

            candidate = result.get("candidate")
            if candidate is None:
                continue

            market_quality = str(
                result.get("market_quality") or "UNKNOWN"
            )
            if market_quality not in {"LOW_SAMPLE", "TEN_DIGIT"}:
                continue

            # Existing ensemble shadow evidence remains separate.
            if learning.has_pending(symbol):
                continue

            model_predictions = dict(
                result.get("model_predictions") or {}
            )
            model_weights = dict(
                result.get("model_weights") or {}
            )
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
