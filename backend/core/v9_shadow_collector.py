"""DSNPFX V9 prospective shadow-learning collector.

The production scanner historically allowed only one global pending prediction.
That is too slow for market-specific calibration and creates a bootstrap
bottleneck. This wrapper keeps production publication unchanged while recording
one non-trading next-tick shadow candidate per eligible Volatility market.

Every record is created before the resolving tick arrives. SHADOW outcomes may
train market-specific model memory; they never bypass the production gate.
"""

from __future__ import annotations

import asyncio

from backend.core.market_family import attach_family_metadata


_ORIGINAL_SCAN_LOOP = None


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


async def _shadow_learning_loop(
    base,
    ai,
    learning,
    latest_ticks,
    quality_gate,
    worker_executor,
    generation,
):
    """Record one prospective SHADOW candidate per live market."""
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
            candidate = result.get("candidate")
            source_tick = latest_ticks.get(symbol)

            if (
                not symbol
                or symbol not in base.VOLATILITY_SYMBOLS
                or candidate is None
                or source_tick is None
                or result.get("status") != "LIVE"
            ):
                continue

            market_quality = str(
                result.get("market_quality") or "UNKNOWN"
            )
            if market_quality not in {"LOW_SAMPLE", "TEN_DIGIT"}:
                continue

            # Exactly one unresolved next-tick record per market prevents
            # overlapping outcomes while allowing all markets to learn in
            # parallel.
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
