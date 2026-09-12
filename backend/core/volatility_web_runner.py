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
        "prediction_source": result.get("prediction_source"),
        "precision_decision": dict(result.get("precision_decision") or {}),
        "adaptive_decision": dict(result.get("adaptive_decision") or {}),
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
    if not live_markets:
        return None

    premium = [
        market
        for market in live_markets
        if market.get("is_premium")
    ]
    if premium:
        return premium[0]

    return live_markets[0]


def _statistics_payload(
    ranked,
    engine,
    quality_gate,
):
    quality_map = (
        quality_gate.assess_all_map()
    )
    qualified = sum(
        quality.classification == "TEN_DIGIT"
        for quality in quality_map.values()
    )

    return {
        "markets_scanned": len(ranked),
        "production_markets": sum(
            market.get("production_eligible", False)
            for market in ranked
        ),
        "shadow_markets": sum(
            not market.get("production_eligible", False)
            for market in ranked
        ),
        "premium_markets": sum(
            market.get("is_premium", False)
            for market in ranked
        ),
        "qualified_markets": qualified,
        "tracked_markets": len(
            engine.markets
        ),
    }


def _state_payload(
    ranked,
    opportunities,
    engine,
    learning,
):
    selected = _select_dashboard_market(
        ranked
    )

    if selected is None:
        return {
            "status": "collecting",
            "message": (
                "Collecting Deriv Volatility tick data..."
            ),
            "decision": "WAIT",
            "prediction": None,
            "confidence": 0.0,
            "edge": 0.0,
            "markets_monitoring": sorted(
                VOLATILITY_SYMBOLS
            ),
            "market_count": len(
                VOLATILITY_SYMBOLS
            ),
            "resolved_predictions": (
                learning.total_resolved()
            ),
        }

    return {
        "status": "live",
        "message": (
            "Verified premium signal available."
            if selected.get("is_premium")
            else "Scanning all Deriv Volatility markets."
        ),
        "decision": (
            "SIGNAL"
            if selected.get("is_premium")
            else "WAIT"
        ),
        "prediction": selected.get(
            "published_prediction"
        ),
        "confidence": _number(
            selected.get("calibrated_confidence")
        ),
        "edge": _number(
            selected.get("edge_score")
        ),
        "market": selected.get("symbol"),
        "markets_monitoring": sorted(
            VOLATILITY_SYMBOLS
        ),
        "market_count": len(
            VOLATILITY_SYMBOLS
        ),
        "resolved_predictions": (
            learning.total_resolved()
        ),
    }


async def run_once():
    generation = _activate_generation()

    discovery = MarketDiscovery()
    engine = MarketEngine()
    model_memory = MarketModelMemory()
    ai = MultiMarketAI(engine, model_memory)
    learning = MultiMarketLearning(
        model_memory=model_memory
    )
    quality_gate = MarketQualityGate()
    accuracy_gate = ProductionAccuracyGate(
        learning=learning,
    )

    executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix=(
            "dsnpfx-market-scan"
        ),
    )

    latest_ticks = {}

    try:
        markets = await discovery.fetch()
        markets = [
            market
            for market in markets
            if market.get("symbol")
            in VOLATILITY_SYMBOLS
        ]

        if not markets:
            raise RuntimeError(
                "No eligible Deriv Volatility "
                "markets discovered"
            )

        discovery_by_symbol = {
            market.get("symbol"): dict(market)
            for market in markets
            if market.get("symbol")
        }

        for market in markets:
            symbol = market["symbol"]
            engine.add_market(symbol)
            family = attach_family_metadata(
                model_memory,
                symbol,
            )
            print(
                "DISCOVERED:",
                symbol,
                market.get("name"),
                "family=",
                family,
            )

        async with websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=5,
            max_queue=None,
        ) as websocket:
            await subscribe_to_markets(
                websocket,
                markets,
            )

            tick_stream = receive_ticks(
                websocket,
                engine,
                discovery_by_symbol,
                latest_ticks,
            )

            async def scanner_loop():
                while True:
                    if not _generation_is_current(
                        generation
                    ):
                        return

                    results = await _run_blocking(
                        executor,
                        ai.scan,
                    )

                    if not _generation_is_current(
                        generation
                    ):
                        return

                    _attach_quality(
                        results,
                        quality_gate,
                    )

                    market_payloads = {
                        result["symbol"]: _market_payload(
                            result,
                            latest_ticks,
                        )
                        for result in results
                        if result.get("symbol")
                    }

                    await _run_blocking(
                        executor,
                        learning.observe,
                        results,
                        latest_ticks,
                    )

                    await _run_blocking(
                        executor,
                        _apply_production_accuracy_gate,
                        market_payloads,
                        accuracy_gate,
                    )

                    if not _generation_is_current(
                        generation
                    ):
                        return

                    ranked = _rank_markets(
                        market_payloads
                    )
                    opportunities = [
                        market
                        for market in ranked
                        if market.get(
                            "is_premium",
                            False,
                        )
                    ]

                    statistics = (
                        _statistics_payload(
                            ranked,
                            engine,
                            quality_gate,
                        )
                    )
                    state = _state_payload(
                        ranked,
                        opportunities,
                        engine,
                        learning,
                    )

                    await publish_state(
                        state,
                        markets={
                            market["symbol"]: market
                            for market in ranked
                        },
                        opportunities=opportunities,
                        statistics=statistics,
                    )

                    await asyncio.sleep(
                        SCAN_INTERVAL
                    )

            scanner_task = asyncio.create_task(
                scanner_loop()
            )

            try:
                await tick_stream
            finally:
                scanner_task.cancel()
                await asyncio.gather(
                    scanner_task,
                    return_exceptions=True,
                )

    finally:
        _invalidate_generation(
            generation
        )
        await asyncio.to_thread(
            _shutdown_executor,
            executor,
        )
        _safe_close(learning)
        _safe_close(model_memory)
        _safe_close(quality_gate)
