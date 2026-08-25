"""
DSNPFX Volatility Website Runner V8 — lifecycle-safe reconnect architecture

Scans only Deriv Volatility indices:

Standard:
    R_10, R_25, R_50, R_75, R_100

One-second:
    1HZ10V, 1HZ25V, 1HZ50V, 1HZ75V, 1HZ100V

Production eligibility:
    Standard R_* markets only.

Shadow learning:
    Standard and one-second Volatility markets.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from itertools import count

import websockets

from backend.core.market_discovery import (
    MarketDiscovery,
)
from backend.core.market_engine import MarketEngine
from backend.core.market_family import (
    attach_family_metadata,
)
from backend.core.market_model_memory import (
    MarketModelMemory,
)
from backend.core.market_quality_gate import (
    MarketQualityGate,
)
from backend.core.multi_market_ai import MultiMarketAI
from backend.core.multi_market_learning import (
    MultiMarketLearning,
)
from backend.core.production_accuracy_gate import (
    ProductionAccuracyGate,
)
from backend.core.multi_market_runner import (
    WS_URL,
    receive_ticks,
    subscribe_to_markets,
)
from backend.web_state import publish_state


STANDARD_VOLATILITY = {
    "R_10",
    "R_25",
    "R_50",
    "R_75",
    "R_100",
}

ONE_SECOND_VOLATILITY = {
    "1HZ10V",
    "1HZ25V",
    "1HZ50V",
    "1HZ75V",
    "1HZ100V",
}

VOLATILITY_SYMBOLS = (
    STANDARD_VOLATILITY
    | ONE_SECOND_VOLATILITY
)

SCAN_INTERVAL = 2
RECONNECT_DELAY = 5

SHADOW_MIN_EDGE = 45.0
SHADOW_MIN_CONFIDENCE = 60.0


# Every connection cycle gets a monotonically increasing generation.
# A stale scanner from an older generation is forbidden from publishing.
_GENERATION_COUNTER = count(1)
_ACTIVE_GENERATION = 0


def _activate_generation() -> int:
    global _ACTIVE_GENERATION
    _ACTIVE_GENERATION = next(_GENERATION_COUNTER)
    return _ACTIVE_GENERATION


def _generation_is_current(generation: int) -> bool:
    return generation == _ACTIVE_GENERATION


def _invalidate_generation(generation: int) -> None:
    global _ACTIVE_GENERATION
    if _ACTIVE_GENERATION == generation:
        _ACTIVE_GENERATION = next(_GENERATION_COUNTER)


def _safe_close(resource) -> None:
    if resource is None:
        return
    close = getattr(resource, "close", None)
    if callable(close):
        close()


def _shutdown_executor(executor: ThreadPoolExecutor) -> None:
    executor.shutdown(wait=True, cancel_futures=True)


async def _run_blocking(
    executor: ThreadPoolExecutor,
    function,
    *args,
):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor,
        function,
        *args,
    )


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _attach_quality(
    results,
    quality_gate,
):
    quality_map = (
        quality_gate.assess_all_map()
    )

    for result in results:
        symbol = result.get("symbol")

        if not symbol:
            continue

        quality = quality_map.get(symbol)

        if quality is None:
            quality = quality_gate.assess(
                symbol
            )

        result["market_quality"] = (
            quality.classification
        )
        result["quality_reason"] = (
            quality.reason
        )
        result["quality_samples"] = (
            quality.resolved_samples
        )
        result["quality_digits"] = (
            quality.distinct_digits
        )
        result["quality_accuracy"] = (
            quality.accuracy
        )


def _market_payload(
    result,
    latest_ticks,
):
    symbol = result.get("symbol")
    tick = latest_ticks.get(symbol, {})

    premium_allowed = (
        symbol in STANDARD_VOLATILITY
        and result.get("market_quality")
        == "TEN_DIGIT"
    )

    production_signal = (
        premium_allowed
        and bool(result.get("premium"))
        and result.get("prediction")
        is not None
    )

    candidate = result.get("candidate")
    model_predictions = dict(
        result.get("model_predictions") or {}
    )
    model_weights = dict(
        result.get("model_weights") or {}
    )

    active_models = int(
        result.get(
            "active_models",
            len(model_predictions),
        )
        or 0
    )

    return {
        "status": (
            "live"
            if result.get("status") == "LIVE"
            else str(
                result.get(
                    "status",
                    "collecting",
                )
            ).lower()
        ),
        "symbol": symbol,
        "price": tick.get("quote"),
        "displayed_price": tick.get(
            "displayed_quote"
        ),
        "last_digit": tick.get("digit"),
        "prediction": (
            result.get("prediction")
            if production_signal
            else None
        ),
        "published_prediction": (
            result.get("prediction")
            if production_signal
            else None
        ),
        "candidate_prediction": candidate,
        "confidence": _number(
            result.get("confidence")
        ),
        "strength": (
            "HIGH"
            if _number(result.get("confidence")) >= 75
            else "MEDIUM"
            if _number(result.get("confidence")) >= 50
            else "LOW"
        ),
        "decision": (
            "SIGNAL"
            if production_signal
            else "WAIT"
        ),
        "premium_status": (
            "PREMIUM OPPORTUNITY"
            if production_signal
            else "NO PREMIUM OPPORTUNITY"
        ),
        "is_premium": production_signal,
        "raw_premium": bool(
            result.get("premium")
        ),
        "edge_score": _number(
            result.get("edge")
        ),
        "edge_grade": result.get(
            "edge_grade",
            "NO EDGE",
        ),
        "edge_components": dict(
            result.get("edge_components") or {}
        ),
        "edge_reasons": list(
            result.get("edge_reasons") or []
        ),
        "blocking_reasons": list(
            result.get("blocking_reasons") or []
        ),
        "confidence_margin": _number(
            result.get("confidence_margin")
        ),
        "regime": result.get(
            "regime",
            "UNKNOWN",
        ),
        "regime_confidence": _number(
            result.get("regime_confidence")
        ),
        "stability_score": _number(
            result.get("stability_score")
        ),
        "active_models": active_models,
        "model_predictions": model_predictions,
        "model_weights": model_weights,
        "model_statistics": dict(
            result.get("model_statistics") or {}
        ),
        "model_metadata": dict(
            result.get("model_metadata") or {}
        ),
        "prediction_sources": {
            model: "MARKET"
            for model in model_predictions
        },
        "market_family": result.get(
            "market_family"
        ),
        "market_quality": result.get(
            "market_quality"
        ),
        "quality_reason": result.get(
            "quality_reason"
        ),
        "quality_samples": result.get(
            "quality_samples",
            0,
        ),
        "quality_digits": result.get(
            "quality_digits",
            0,
        ),
        "quality_accuracy": result.get(
            "quality_accuracy",
            0,
        ),
        "production_eligible": (
            symbol in STANDARD_VOLATILITY
        ),
        "mode": (
            "PRODUCTION"
            if symbol in STANDARD_VOLATILITY
            else "SHADOW"
        ),
        "outcome": None,
        "specialist_activation": (
            "MARKET-SPECIFIC"
        ),
    }


def _rank_markets(markets):
    return sorted(
        markets.values(),
        key=lambda market: (
            market.get("is_premium", False),
            _number(
                market.get("edge_score")
            ),
            _number(
                market.get("confidence")
            ),
        ),
        reverse=True,
    )


def _apply_production_accuracy_gate(
    markets,
    accuracy_gate,
):
    """
    Convert raw candidates into verified production decisions.

    No market may retain SIGNAL status unless it passes the
    complete evidence-based Production Accuracy Gate.
    """

    for market in markets.values():
        evaluation = accuracy_gate.evaluate(
            market
        )

        market["raw_confidence"] = (
            evaluation["raw_confidence"]
        )

        market["calibrated_confidence"] = (
            evaluation[
                "calibrated_confidence"
            ]
        )

        market["rolling_accuracy"] = (
            evaluation["rolling_accuracy"]
        )

        market["rolling_samples"] = (
            evaluation["rolling_samples"]
        )

        market["lifetime_accuracy"] = (
            evaluation["lifetime_accuracy"]
        )

        market["lifetime_samples"] = (
            evaluation["lifetime_samples"]
        )

        market["model_agreement"] = (
            evaluation["agreement"]
        )

        market["evidence_scope"] = (
            evaluation["evidence_scope"]
        )

        market["rolling_lower_bound"] = (
            evaluation["rolling_lower_bound"]
        )

        market["rolling_upper_bound"] = (
            evaluation["rolling_upper_bound"]
        )

        market["last20_accuracy"] = (
            evaluation["last20_accuracy"]
        )

        market["last20_samples"] = (
            evaluation["last20_samples"]
        )

        market["last50_accuracy"] = (
            evaluation["last50_accuracy"]
        )

        market["last50_samples"] = (
            evaluation["last50_samples"]
        )

        market["last50_upper_bound"] = (
            evaluation["last50_upper_bound"]
        )

        market["last100_accuracy"] = (
            evaluation["last100_accuracy"]
        )

        market["last100_samples"] = (
            evaluation["last100_samples"]
        )

        market["current_streak_result"] = (
            evaluation[
                "current_streak_result"
            ]
        )

        market["current_streak_count"] = (
            evaluation[
                "current_streak_count"
            ]
        )

        market["statistically_above_baseline"] = (
            evaluation[
                "statistically_above_baseline"
            ]
        )

        market["recent_deterioration"] = (
            evaluation[
                "recent_deterioration"
            ]
        )

        market["market_qualified"] = (
            evaluation[
                "market_qualified"
            ]
        )

        market["is_premium"] = (
            evaluation["approved"]
        )

        market["decision"] = (
            evaluation["decision"]
        )

        market["prediction"] = (
            evaluation[
                "published_prediction"
            ]
        )

        market["published_prediction"] = (
            evaluation[
                "published_prediction"
            ]
        )

        market["premium_status"] = (
            "VERIFIED PREMIUM OPPORTUNITY"
            if evaluation["approved"]
            else "NO VERIFIED OPPORTUNITY"
        )

        existing_reasons = list(
            market.get(
                "blocking_reasons",
                [],
            )
        )

        market["blocking_reasons"] = list(
            dict.fromkeys(
                existing_reasons
                + evaluation[
                    "blocking_reasons"
                ]
            )
        )


def _select_dashboard_market(
    ranked,
):
    live_markets = [
        market
        for market in ranked
        if market.get("status") == "live"
    ]

    production_signals = [
        market
        for market in live_markets
        if market.get("is_premium")
    ]

    if production_signals:
        return production_signals[0]

    standard_candidates = [
        market
        for market in live_markets
        if market.get(
            "production_eligible"
        )
    ]

    if standard_candidates:
        return standard_candidates[0]

    if live_markets:
        return live_markets[0]

    return {
        "status": "collecting",
        "symbol": "R_100",
        "message": (
            "Collecting volatility market data..."
        ),
        "decision": "WAIT",
        "is_premium": False,
    }


def _opportunity_payload(ranked):
    return [
        {
            "symbol": market.get("symbol"),
            "candidate_prediction": (
                market.get(
                    "candidate_prediction"
                )
            ),
            "published_prediction": (
                market.get(
                    "published_prediction"
                )
            ),
            "confidence": market.get(
                "confidence"
            ),
            "edge_score": market.get(
                "edge_score"
            ),
            "edge_grade": market.get(
                "edge_grade"
            ),
            "regime": market.get(
                "regime"
            ),
            "market_quality": market.get(
                "market_quality"
            ),
            "mode": market.get("mode"),
            "decision": market.get(
                "decision"
            ),
            "is_premium": market.get(
                "is_premium"
            ),
            "blocking_reasons": (
                market.get(
                    "blocking_reasons",
                    [],
                )
            ),
        }
        for market in ranked
    ]


async def _scan_loop(
    ai,
    learning,
    latest_ticks,
    quality_gate,
    accuracy_gate,
    worker_executor,
    generation,
):
    while True:
        await asyncio.sleep(
            SCAN_INTERVAL
        )

        results = await _run_blocking(
            worker_executor,
            ai.scan,
        )

        if not _generation_is_current(generation):
            return

        if not results:
            continue

        attach_family_metadata(results)

        await _run_blocking(
            worker_executor,
            _attach_quality,
            results,
            quality_gate,
        )

        if not _generation_is_current(generation):
            return

        markets = {
            result["symbol"]: (
                _market_payload(
                    result,
                    latest_ticks,
                )
            )
            for result in results
            if result.get("symbol")
            in VOLATILITY_SYMBOLS
        }

        await _run_blocking(
            worker_executor,
            _apply_production_accuracy_gate,
            markets,
            accuracy_gate,
        )

        if not _generation_is_current(generation):
            return

        ranked = _rank_markets(markets)
        dashboard = _select_dashboard_market(
            ranked
        )

        statistics = learning.honest_statistics(
            rolling_limit=100
        )

        no_pending = (
            statistics.get("pending", 0)
            == 0
        )

        if no_pending:
            production = next(
                (
                    market
                    for market in ranked
                    if market.get("is_premium")
                ),
                None,
            )

            shadow = next(
                (
                    market
                    for market in ranked
                    if (
                        market.get("candidate_prediction")
                        is not None
                        and market.get("market_quality")
                        in {
                            "TEN_DIGIT",
                            "LOW_SAMPLE",
                        }
                        and _number(
                            market.get("edge_score")
                        ) >= SHADOW_MIN_EDGE
                        and _number(
                            market.get("confidence")
                        ) >= SHADOW_MIN_CONFIDENCE
                    )
                ),
                None,
            )

            research_candidates = [
                market
                for market in ranked
                if (
                    market.get("candidate_prediction")
                    is not None
                    and market.get("market_quality")
                    in {
                        "TEN_DIGIT",
                        "LOW_SAMPLE",
                    }
                    and sum(
                        1
                        for weight in (
                            market.get("model_weights")
                            or {}
                        ).values()
                        if _number(weight) > 0.0
                    ) >= 2
                    and bool(
                        market.get("model_predictions")
                    )
                )
            ]

            research = None

            if research_candidates:
                research_count = int(
                    (
                        statistics.get("research")
                        or {}
                    ).get(
                        "resolved",
                        0,
                    )
                )

                research = research_candidates[
                    research_count
                    % len(research_candidates)
                ]

            if production is not None:
                selected = production
                selection_mode = "PREMIUM"

            elif shadow is not None:
                selected = shadow
                selection_mode = "SHADOW"

            else:
                selected = research
                selection_mode = (
                    "RESEARCH"
                    if research is not None
                    else None
                )

            if selected is not None:
                symbol = selected["symbol"]
                source_tick = latest_ticks.get(
                    symbol
                )

                if source_tick is not None:
                    record = {
                        "symbol": symbol,
                        "prediction": (
                            selected.get(
                                "published_prediction"
                            )
                            if selection_mode == "PREMIUM"
                            else None
                        ),
                        "candidate": selected.get(
                            "candidate_prediction"
                        ),
                        "confidence": selected.get(
                            "confidence"
                        ),
                        "edge": selected.get(
                            "edge_score"
                        ),
                        "edge_grade": selected.get(
                            "edge_grade"
                        ),
                        "regime": selected.get(
                            "regime"
                        ),
                        "model_predictions": selected.get(
                            "model_predictions",
                            {},
                        ),
                        "model_weights": selected.get(
                            "model_weights",
                            {},
                        ),

                        # V8.3 Phase 3A telemetry snapshot.
                        # These fields are observational only.
                        "edge_components": selected.get(
                            "edge_components",
                            {},
                        ),
                        "model_statistics": selected.get(
                            "model_statistics",
                            {},
                        ),
                        "regime_confidence": selected.get(
                            "regime_confidence"
                        ),
                        "stability_score": selected.get(
                            "stability_score"
                        ),
                        "confidence_margin": selected.get(
                            "confidence_margin"
                        ),

                        "calibrated_confidence": selected.get(
                            "calibrated_confidence"
                        ),
                        "rolling_accuracy": selected.get(
                            "rolling_accuracy"
                        ),
                        "rolling_samples": selected.get(
                            "rolling_samples"
                        ),
                        "rolling_lower_bound": selected.get(
                            "rolling_lower_bound"
                        ),
                        "rolling_upper_bound": selected.get(
                            "rolling_upper_bound"
                        ),

                        "last20_accuracy": selected.get(
                            "last20_accuracy"
                        ),
                        "last20_samples": selected.get(
                            "last20_samples"
                        ),

                        "last50_accuracy": selected.get(
                            "last50_accuracy"
                        ),
                        "last50_samples": selected.get(
                            "last50_samples"
                        ),
                        "last50_upper_bound": selected.get(
                            "last50_upper_bound"
                        ),

                        "last100_accuracy": selected.get(
                            "last100_accuracy"
                        ),
                        "last100_samples": selected.get(
                            "last100_samples"
                        ),

                        "market_qualified": selected.get(
                            "market_qualified"
                        ),
                        "statistically_above_baseline": (
                            selected.get(
                                "statistically_above_baseline"
                            )
                        ),
                        "recent_deterioration": selected.get(
                            "recent_deterioration"
                        ),
                        "evidence_scope": selected.get(
                            "evidence_scope"
                        ),

                        "current_streak_result": selected.get(
                            "current_streak_result"
                        ),
                        "current_streak_count": selected.get(
                            "current_streak_count"
                        ),

                        "premium": (
                            selection_mode == "PREMIUM"
                        ),
                        "source_epoch": (
                            source_tick["epoch"]
                        ),
                        "source_quote": (
                            source_tick["quote"]
                        ),
                    }

                    if not _generation_is_current(
                        generation
                    ):
                        return

                    saved = learning.create_prediction(
                        record
                    )

                    if saved:
                        learning.tag_pending_prediction(
                            symbol,
                            selection_mode=selection_mode,
                            market_family=selected.get(
                                "market_family",
                                "UNKNOWN",
                            ),
                            market_quality=selected.get(
                                "market_quality",
                                "UNKNOWN",
                            ),
                        )

        if not _generation_is_current(generation):
            return

        dashboard_state = {
            **dashboard,
            "markets_monitoring": sorted(
                VOLATILITY_SYMBOLS
            ),
            "market_count": len(markets),
            "live_market_count": sum(
                1
                for market in markets.values()
                if market.get("status") == "live"
            ),
            "message": (
                "Scanning all Volatility indices. "
                "Only validated standard Volatility "
                "signals are published."
            ),
            "honest_statistics": statistics,
            "runner_generation": generation,
        }

        await publish_state(
            dashboard_state,
            markets=markets,
            opportunities=_opportunity_payload(
                ranked
            ),
            statistics=statistics,
        )


async def run_once():
    generation = _activate_generation()

    discovery = MarketDiscovery()
    discovered = await discovery.fetch()

    markets = [
        market
        for market in discovered
        if market.get("symbol")
        in VOLATILITY_SYMBOLS
    ]

    discovered_symbols = {
        market["symbol"]
        for market in markets
    }

    missing = (
        VOLATILITY_SYMBOLS
        - discovered_symbols
    )

    if missing:
        _invalidate_generation(generation)
        raise RuntimeError(
            "Required Volatility markets "
            f"not discovered: {sorted(missing)}"
        )

    market_engine = MarketEngine(
        max_history=1000
    )

    latest_ticks = {}

    model_memory = MarketModelMemory(
        database=(
            "backend/data/"
            "market_model_memory.db"
        )
    )

    learning = MultiMarketLearning(
        model_memory=model_memory,
        database=(
            "backend/data/"
            "multi_market_learning.db"
        ),
    )

    ai = MultiMarketAI(
        market_engine,
        model_memory,
    )

    quality_gate = MarketQualityGate(
        database=(
            "backend/data/"
            "multi_market_learning.db"
        ),
        min_samples=100,
        min_distinct_digits=10,
        max_top_digit_share=30.0,
    )

    accuracy_gate = ProductionAccuracyGate(
        database=(
            "backend/data/"
            "multi_market_learning.db"
        ),
        minimum_samples=100,
        rolling_window=100,
        minimum_rolling_accuracy=15.0,
        minimum_edge=70.0,
        minimum_raw_confidence=66.0,
        minimum_agreeing_models=2,
    )

    worker_executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix=(
            f"dsnpfx-scan-{generation}"
        ),
    )

    receiver = None
    scanner = None

    await publish_state(
        {
            "status": "collecting",
            "symbol": "R_100",
            "message": (
                "Connecting to 10 Volatility markets..."
            ),
            "markets_monitoring": sorted(
                VOLATILITY_SYMBOLS
            ),
            "market_count": len(markets),
            "decision": "WAIT",
            "is_premium": False,
            "runner_generation": generation,
        },
        markets={},
        opportunities=[],
        statistics=learning.honest_statistics(
            rolling_limit=100
        ),
    )

    try:
        async with websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=90,
            close_timeout=10,
            max_queue=None,
        ) as websocket:
            print(
                "DSNPFX VOLATILITY WEB RUNNER V8"
            )
            print(
                f"Generation: {generation}"
            )
            print(
                f"Subscribed markets: {len(markets)}"
            )

            for market in markets:
                print(
                    " ",
                    market["symbol"],
                    "|",
                    market["name"],
                )

            await subscribe_to_markets(
                websocket,
                markets,
            )

            receiver = asyncio.create_task(
                receive_ticks(
                    websocket,
                    market_engine,
                    learning,
                    latest_ticks,
                ),
                name=f"dsnpfx-receiver-{generation}",
            )

            scanner = asyncio.create_task(
                _scan_loop(
                    ai,
                    learning,
                    latest_ticks,
                    quality_gate,
                    accuracy_gate,
                    worker_executor,
                    generation,
                ),
                name=f"dsnpfx-scanner-{generation}",
            )

            done, pending = await asyncio.wait(
                {
                    receiver,
                    scanner,
                },
                return_when=(
                    asyncio.FIRST_EXCEPTION
                ),
            )

            _invalidate_generation(
                generation
            )

            for task in pending:
                task.cancel()

            await asyncio.gather(
                *pending,
                return_exceptions=True,
            )

            for task in done:
                if task.cancelled():
                    continue

                exception = task.exception()

                if exception is not None:
                    raise exception

    finally:
        _invalidate_generation(
            generation
        )

        tasks = [
            task
            for task in (
                receiver,
                scanner,
            )
            if task is not None
            and not task.done()
        ]

        for task in tasks:
            task.cancel()

        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )

        # Critical ordering:
        # 1. asyncio tasks stop.
        # 2. worker thread drains fully.
        # 3. SQLite-backed resources close.
        _shutdown_executor(
            worker_executor
        )

        _safe_close(accuracy_gate)
        _safe_close(quality_gate)
        _safe_close(learning)
        _safe_close(model_memory)


async def run_forever():
    while True:
        try:
            await run_once()

        except asyncio.CancelledError:
            raise

        except Exception as error:
            print(
                "VOLATILITY WEBSITE ERROR:",
                type(error).__name__,
                error,
            )

            await publish_state(
                {
                    "status": "reconnecting",
                    "message": (
                        "Volatility feed disconnected. "
                        "Lifecycle-safe reconnect starting..."
                    ),
                    "decision": "WAIT",
                    "is_premium": False,
                    "markets_monitoring": sorted(
                        VOLATILITY_SYMBOLS
                    ),
                    "market_count": 10,
                },
            )

            await asyncio.sleep(
                RECONNECT_DELAY
            )
