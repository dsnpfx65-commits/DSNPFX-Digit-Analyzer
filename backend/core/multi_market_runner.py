import asyncio
import json

import websockets

from backend.core.market_discovery import MarketDiscovery
from backend.core.market_engine import MarketEngine
from backend.core.market_family import (
    attach_family_metadata,
    family_leaders,
    select_overall_premium_leader,
)
from backend.core.market_quality_gate import MarketQualityGate
from backend.core.market_model_memory import MarketModelMemory
from backend.core.multi_market_ai import MultiMarketAI
from backend.core.multi_market_learning import MultiMarketLearning


WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

SCAN_INTERVAL = 2
RECONNECT_DELAY = 5

# Shadow-learning thresholds.
# These predictions train the analyzer only.
# They are not premium signals and must not be traded.
LEARNING_MIN_EDGE = 15.0
LEARNING_MIN_CONFIDENCE = 66.0


async def subscribe_to_markets(ws, markets):
    for market in markets:
        symbol = market["symbol"]

        await ws.send(
            json.dumps(
                {
                    "ticks": symbol,
                    "subscribe": 1,
                }
            )
        )

        await asyncio.sleep(0.05)


def format_tick_quote(
    quote,
    pip_size,
) -> str | None:
    """
    Format a Deriv quote using the market's official
    decimal precision.

    JSON numbers can lose trailing zeros. For example,
    249.20 may arrive as 249.2. The pip size restores
    the correct representation before digit extraction.
    """
    if quote is None or pip_size is None:
        return None

    try:
        precision = int(pip_size)
        numeric_quote = float(quote)
    except (TypeError, ValueError):
        return None

    return f"{numeric_quote:.{precision}f}"


def extract_last_digit(
    quote,
    pip_size,
) -> tuple[int, str] | None:
    formatted_quote = format_tick_quote(
        quote,
        pip_size,
    )

    if formatted_quote is None:
        return None

    final_character = formatted_quote[-1]

    if not final_character.isdigit():
        return None

    return int(final_character), formatted_quote


def print_resolved_result(resolved):
    print("\nPREDICTION RESOLVED")
    print("------------------------")
    print(f"Symbol: {resolved['symbol']}")
    print(f"Prediction: {resolved['predicted']}")
    print(f"Actual: {resolved['actual']}")
    print(f"Result: {resolved['result']}")
    print(f"Edge: {resolved['edge']}")
    print(f"Regime: {resolved['regime']}")
    print(
        f"Tick Epoch: {resolved['source_epoch']} "
        f"-> {resolved['resolved_epoch']}"
    )
    print(
        f"Tick Quote: {resolved['source_quote']} "
        f"-> {resolved['resolved_quote']}"
    )

    model_results = resolved.get(
        "model_results",
        {},
    )

    if model_results:
        print("Model Results:")

        for model, details in model_results.items():
            print(
                f"  {model}: "
                f"{details['prediction']} -> "
                f"{details['result']}"
            )

    print("------------------------")


async def receive_ticks(
    ws,
    market_engine,
    learning,
    latest_ticks,
):
    # DSNPFX_TICK_ARCHIVE_V83
    #
    # Observational archive only. This database is used by
    # offline V9 evaluation and is never consulted when making
    # a live V8.3 prediction.
    from backend.core.tick_archive import (
        MultiMarketTickArchive,
    )

    tick_archive = MultiMarketTickArchive()

    try:
        while True:
            message = await ws.recv()
            data = json.loads(message)

            if data.get("error"):
                print(
                    "DERIV ERROR:",
                    data["error"].get(
                        "message",
                        data["error"],
                    ),
                )
                continue

            tick = data.get("tick")

            if not tick:
                continue

            symbol = tick.get("symbol")
            quote = tick.get("quote")
            epoch = tick.get("epoch")
            pip_size = tick.get("pip_size")

            if (
                symbol is None
                or quote is None
                or epoch is None
                or pip_size is None
            ):
                continue

            epoch = int(epoch)

            previous_tick = latest_ticks.get(symbol)

            # Ignore duplicate, stale, or replayed ticks.
            if (
                previous_tick is not None
                and epoch <= previous_tick["epoch"]
            ):
                continue

            digit_result = extract_last_digit(
                quote,
                pip_size,
            )

            if digit_result is None:
                continue

            last_digit, formatted_quote = digit_result

            # DSNPFX V8.3 Phase 3A.2:
            # archive the accepted tick for offline research.
            #
            # This occurs after the exact displayed last digit
            # has been established. INSERT OR IGNORE makes the
            # operation idempotent across reconnects/restarts.
            await asyncio.to_thread(
                tick_archive.add_tick,
                symbol=symbol,
                quote=quote,
                displayed_quote=formatted_quote,
                digit=last_digit,
                epoch=epoch,
                pip_size=pip_size,
            )

            # Resolve a previously published signal before
            # adding this new digit to market history.
            resolved = learning.resolve(
                symbol,
                last_digit,
                tick_epoch=epoch,
                tick_quote=formatted_quote,
            )

            if resolved is not None:
                print_resolved_result(resolved)

            market_engine.add_tick(
                symbol,
                last_digit,
            )

            latest_ticks[symbol] = {
                "epoch": epoch,
                "quote": formatted_quote,
                "displayed_quote": formatted_quote,
                "digit": last_digit,
                "pip_size": int(pip_size),
            }

    except websockets.exceptions.ConnectionClosedOK:
        return

    finally:
        tick_archive.close()


def print_learning_statistics(learning):
    """
    Print only separated, auditable performance statistics.

    The historical all-market total is intentionally not shown
    as trusted accuracy because it contains legacy and
    constrained-market results.
    """

    stats = learning.honest_statistics(
        rolling_limit=100
    )

    production = stats["production"]
    production_recent = stats[
        "production_rolling"
    ]

    shadow = stats["shadow"]
    shadow_recent = stats[
        "shadow_rolling"
    ]

    constrained = stats["constrained"]
    legacy = stats["legacy"]

    print("\nHONEST PERFORMANCE STATISTICS")
    print("------------------------")

    print(
        "Production Signals: "
        f"{production['wins']}W / "
        f"{production['losses']}L | "
        f"Accuracy: {production['accuracy']}% | "
        f"Resolved: {production['resolved']}"
    )

    print(
        "Production Last 100: "
        f"{production_recent['wins']}W / "
        f"{production_recent['losses']}L | "
        f"Accuracy: "
        f"{production_recent['accuracy']}% | "
        f"Resolved: "
        f"{production_recent['resolved']}"
    )

    print(
        "Shadow Learning: "
        f"{shadow['wins']}W / "
        f"{shadow['losses']}L | "
        f"Accuracy: {shadow['accuracy']}% | "
        f"Resolved: {shadow['resolved']}"
    )

    print(
        "Shadow Last 100: "
        f"{shadow_recent['wins']}W / "
        f"{shadow_recent['losses']}L | "
        f"Accuracy: "
        f"{shadow_recent['accuracy']}% | "
        f"Resolved: "
        f"{shadow_recent['resolved']}"
    )

    print(
        "Constrained Research: "
        f"{constrained['wins']}W / "
        f"{constrained['losses']}L | "
        f"Resolved: {constrained['resolved']}"
    )

    print(
        "Legacy History: "
        f"{legacy['wins']}W / "
        f"{legacy['losses']}L | "
        f"Resolved: {legacy['resolved']} | "
        "Not trusted as production accuracy"
    )

    print(
        f"Pending Predictions: {stats['pending']}"
    )



async def scan_markets(
    ai,
    learning,
    latest_ticks,
    quality_gate,
):
    while True:
        await asyncio.sleep(SCAN_INTERVAL)

        print("\nScanning...")

        results = await asyncio.to_thread(
            ai.scan
        )

        if not results:
            print(
                "No markets available for analysis."
            )
            continue

        live_results = [
            result
            for result in results
            if result.get("status") == "LIVE"
        ]

        quality_snapshot = (
            quality_gate.assess_all_map()
        )

        attach_family_metadata(results)

        for result in results:
            symbol = result.get("symbol")
            quality = quality_snapshot.get(symbol)

            if quality is None and symbol:
                quality = quality_gate.assess(
                    symbol
                )

            if quality is None:
                continue

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

        leaders = family_leaders(
            live_results
        )

        print("\nFAMILY LEADERS")
        print("------------------------")

        for family in sorted(leaders):
            leader = leaders[family]

            print(
                f"{family:<16} | "
                f"{leader.get('symbol'):<10} | "
                f"Candidate: "
                f"{leader.get('candidate')} | "
                f"Confidence: "
                f"{leader.get('confidence')} | "
                f"Edge: {leader.get('edge')} | "
                f"Quality: "
                f"{leader.get('market_quality')}"
            )

        print("------------------------")

        overall_premium_leader = (
            select_overall_premium_leader(
                leaders
            )
        )

        premium_results = []

        if (
            overall_premium_leader is not None
            and not learning.has_pending(
                overall_premium_leader.get(
                    "symbol"
                )
            )
        ):
            premium_results = [
                overall_premium_leader
            ]

        shadow_learning_results = [
            result
            for result in live_results
            if result.get("candidate") is not None
            and result.get("family_shadow_eligible")
            and result.get("market_quality") in {
                "TEN_DIGIT",
                "LOW_SAMPLE",
            }
            and float(result.get("edge", 0)) >= LEARNING_MIN_EDGE
            and float(result.get("confidence", 0)) >= (
                LEARNING_MIN_CONFIDENCE
            )
            and not learning.has_pending(
                result.get("symbol")
            )
        ]

        # Only approved family leaders can become production
        # premium opportunities. Every fallback candidate is
        # strictly a shadow-learning sample.
        selection_mode = (
            "PREMIUM"
            if premium_results
            else "SHADOW"
        )

        eligible_results = (
            premium_results
            if premium_results
            else shadow_learning_results
        )

        if eligible_results:
            best = eligible_results[0]
            symbol = best.get("symbol")
            source_tick = latest_ticks.get(symbol)

            if source_tick is None:
                print(
                    "Latest source tick unavailable; "
                    "prediction skipped."
                )
                continue

            # Copy the opportunity so audit metadata does not
            # modify the AI result object.
            prediction_record = dict(best)

            prediction_record["premium"] = (
                selection_mode == "PREMIUM"
            )

            if selection_mode != "PREMIUM":
                prediction_record["prediction"] = None

            prediction_record["source_epoch"] = (
                source_tick["epoch"]
            )
            prediction_record["source_quote"] = (
                source_tick["quote"]
            )

            saved = learning.create_prediction(
                prediction_record
            )

            if saved:
                tagged = (
                    learning.tag_pending_prediction(
                        symbol,
                        selection_mode=selection_mode,
                        market_family=best.get(
                            "market_family",
                            "UNKNOWN",
                        ),
                        market_quality=best.get(
                            "market_quality",
                            "UNKNOWN",
                        ),
                    )
                )

                if not tagged:
                    raise RuntimeError(
                        "Saved prediction could not be "
                        "tagged with audit metadata"
                    )
                is_production_premium = (
                    selection_mode == "PREMIUM"
                )

                opportunity_type = (
                    "PREMIUM OPPORTUNITY"
                    if is_production_premium
                    else "SHADOW LEARNING SAMPLE"
                )

                print(
                    f"\nBEST {opportunity_type}"
                )
                print("------------------------")
                print(
                    f"Symbol: {best.get('symbol')}"
                )
                if selection_mode == "PREMIUM":
                    print(
                        f"Published Prediction: "
                        f"{best.get('prediction')}"
                    )
                    print(
                        f"Candidate: "
                        f"{best.get('candidate')}"
                    )
                else:
                    print(
                        f"Training Candidate: "
                        f"{best.get('candidate')}"
                    )
                print(
                    f"Confidence: "
                    f"{best.get('confidence')}"
                )
                print(
                    f"Edge: {best.get('edge')}"
                )
                print(
                    f"Grade: "
                    f"{best.get('edge_grade')}"
                )
                print(
                    f"Regime: "
                    f"{best.get('regime')}"
                )
                print(
                    f"Market Quality: "
                    f"{best.get('market_quality')}"
                )
                print(
                    f"Market Family: "
                    f"{best.get('market_family')}"
                )
                print(
                    "Status: WAITING FOR "
                    "NEXT SYMBOL TICK"
                )

                if selection_mode != "PREMIUM":
                    print(
                        "Usage: TRAINING ONLY — "
                        "NOT A TRADE SIGNAL"
                    )
                print("------------------------")

                print_learning_statistics(
                    learning
                )

            continue

        collecting = [
            result
            for result in results
            if result.get("status") == "COLLECTING"
        ]

        errors = [
            result
            for result in results
            if result.get("status") == "ERROR"
        ]

        blocked_by_pending = [
            result
            for result in live_results
            if result.get("premium")
            and learning.has_pending(
                result.get("symbol")
            )
        ]

        if blocked_by_pending:
            print(
                "Eligible markets already have "
                "pending predictions."
            )
        else:
            print(
                "No learning opportunities found."
            )

        print(
            f"Live: {len(live_results)} | "
            f"Collecting: {len(collecting)} | "
            f"Errors: {len(errors)}"
        )

        print_learning_statistics(learning)

        rejected = [
            result
            for result in live_results
            if not result.get("premium")
        ]

        if rejected:
            print("\nTOP REJECTED MARKETS")
            print("------------------------")

            for result in rejected[:5]:
                reasons = (
                    result.get(
                        "blocking_reasons"
                    )
                    or []
                )

                reason_text = (
                    "; ".join(reasons)
                    or "Unknown blocker"
                )

                print(
                    f"{result.get('symbol')} | "
                    f"Candidate: "
                    f"{result.get('candidate')} | "
                    f"Confidence: "
                    f"{result.get('confidence')} | "
                    f"Edge: "
                    f"{result.get('edge')} | "
                    f"Grade: "
                    f"{result.get('edge_grade')}"
                )
                print(
                    f"Blocked: {reason_text}"
                )

            print("------------------------")

        if errors:
            print("\nAI ERRORS")

            for result in errors[:5]:
                print(
                    f"{result.get('symbol')}: "
                    f"{result.get('error')}"
                )


async def run_scanner():
    discovery = MarketDiscovery()
    markets = await discovery.fetch()

    if not markets:
        raise RuntimeError(
            "No supported Deriv synthetic "
            "markets discovered."
        )

    print(f"Found {len(markets)} markets")

    market_engine = MarketEngine()

    # Latest accepted Deriv tick identity for every symbol.
    latest_ticks = {}

    model_memory = MarketModelMemory(
        database=(
            "backend/data/"
            "market_model_memory.db"
        ),
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

    try:
        async with websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=90,
            close_timeout=10,
            max_queue=None,
        ) as ws:
            print(
                "Connected to Deriv WebSocket"
            )

            await subscribe_to_markets(
                ws,
                markets,
            )

            print(
                f"Subscribed to "
                f"{len(markets)} markets"
            )

            receiver_task = asyncio.create_task(
                receive_ticks(
                    ws,
                    market_engine,
                    learning,
                    latest_ticks,
                )
            )

            scanner_task = asyncio.create_task(
                scan_markets(
                    ai,
                    learning,
                    latest_ticks,
                    quality_gate,
                )
            )

            done, pending = await asyncio.wait(
                {
                    receiver_task,
                    scanner_task,
                },
                return_when=(
                    asyncio.FIRST_EXCEPTION
                ),
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

                if exception:
                    raise exception

    finally:
        learning.close()
        model_memory.close()


async def main():
    while True:
        try:
            await run_scanner()

        except asyncio.CancelledError:
            raise

        except KeyboardInterrupt:
            break

        except Exception as error:
            print(
                f"\nCONNECTION ERROR: {error}"
            )
            print(
                f"Reconnecting in "
                f"{RECONNECT_DELAY} seconds..."
            )

            await asyncio.sleep(
                RECONNECT_DELAY
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("\nScanner stopped.")
