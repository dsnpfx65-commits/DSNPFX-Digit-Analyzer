from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import websockets


_PRECISION_BY_SYMBOL: dict[str, int] = {}
_MARKET_HEALTH: dict[str, dict[str, Any]] = {}
_RUNTIME_TOTALS = {
    "ticks_seen": 0,
    "ticks_accepted": 0,
    "tick_precision": 0,
    "metadata_precision": 0,
    "missing_precision": 0,
    "invalid_tick": 0,
    "stale_tick": 0,
    "format_rejected": 0,
}


def normalize_precision(value: Any) -> int | None:
    """Normalize Deriv precision metadata to decimal places.

    Deriv metadata can represent precision either as an integer number of
    decimal places (for example ``3``) or as a decimal increment (for example
    ``0.001``). Invalid, negative, zero-increment, or non-finite values are
    rejected.
    """
    if value is None or isinstance(value, bool):
        return None

    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if not decimal_value.is_finite():
        return None

    if decimal_value == decimal_value.to_integral_value():
        integer = int(decimal_value)
        return integer if integer >= 0 else None

    if Decimal("0") < decimal_value < Decimal("1"):
        normalized = decimal_value.normalize()
        exponent = normalized.as_tuple().exponent
        return max(0, -exponent)

    return None


def _health_record(symbol: str) -> dict[str, Any]:
    return _MARKET_HEALTH.setdefault(
        symbol,
        {
            "symbol": symbol,
            "subscribed": False,
            "metadata_precision": None,
            "ticks_seen": 0,
            "ticks_accepted": 0,
            "last_epoch": None,
            "last_received_monotonic": None,
            "last_displayed_quote": None,
            "last_digit": None,
            "precision": None,
            "precision_source": None,
            "quote_source": "DERIV_OPTIONS_TICK_QUOTE",
            "last_rejection": None,
        },
    )


def record_market_precisions(markets) -> dict[str, int]:
    for market in markets or []:
        symbol = market.get("symbol") if isinstance(market, dict) else None
        if not symbol:
            continue
        symbol = str(symbol)
        health = _health_record(symbol)
        health["subscribed"] = True
        precision = normalize_precision(market.get("pip_size"))
        health["metadata_precision"] = precision
        if precision is not None:
            _PRECISION_BY_SYMBOL[symbol] = precision
    return dict(_PRECISION_BY_SYMBOL)


def get_market_precision(symbol: str | None) -> int | None:
    if not symbol:
        return None
    return _PRECISION_BY_SYMBOL.get(str(symbol))


def resolve_tick_precision(symbol: str | None, tick_pip_size: Any) -> tuple[int | None, str]:
    tick_precision = normalize_precision(tick_pip_size)
    if tick_precision is not None:
        if symbol:
            _PRECISION_BY_SYMBOL[str(symbol)] = tick_precision
        return tick_precision, "TICK"

    market_precision = get_market_precision(symbol)
    if market_precision is not None:
        return market_precision, "MARKET_METADATA"

    return None, "MISSING"


def format_quote_exact(quote: Any, precision: Any) -> str | None:
    normalized_precision = normalize_precision(precision)
    if quote is None or normalized_precision is None:
        return None

    try:
        decimal_quote = Decimal(str(quote))
    except (InvalidOperation, ValueError, TypeError):
        return None

    if not decimal_quote.is_finite():
        return None

    return f"{decimal_quote:.{normalized_precision}f}"


def extract_last_digit_exact(quote: Any, precision: Any) -> tuple[int, str] | None:
    displayed_quote = format_quote_exact(quote, precision)
    if displayed_quote is None or not displayed_quote[-1].isdigit():
        return None
    return int(displayed_quote[-1]), displayed_quote


def get_precision_runtime_snapshot() -> dict[str, Any]:
    now = time.monotonic()
    markets = []

    for symbol in sorted(_MARKET_HEALTH):
        item = dict(_MARKET_HEALTH[symbol])
        last_received = item.pop("last_received_monotonic", None)
        age_seconds = None
        if last_received is not None:
            age_seconds = round(max(0.0, now - float(last_received)), 3)

        accepted = int(item.get("ticks_accepted") or 0)
        subscribed = bool(item.get("subscribed"))
        if accepted > 0 and age_seconds is not None and age_seconds <= 15.0:
            health = "HEALTHY"
        elif accepted > 0:
            health = "STALE"
        elif subscribed:
            health = "WAITING_FOR_TICK"
        else:
            health = "UNKNOWN"

        item["quote_age_seconds"] = age_seconds
        item["health"] = health
        markets.append(item)

    return {
        "totals": dict(_RUNTIME_TOTALS),
        "tracked_markets": len(markets),
        "healthy_markets": sum(1 for item in markets if item["health"] == "HEALTHY"),
        "stale_markets": sum(1 for item in markets if item["health"] == "STALE"),
        "waiting_markets": sum(1 for item in markets if item["health"] == "WAITING_FOR_TICK"),
        "markets": markets,
    }


async def precision_receive_ticks(ws, market_engine, learning, latest_ticks):
    """Receive Deriv Options ticks with precision fallback and health telemetry."""
    from backend.core.tick_archive import MultiMarketTickArchive
    from backend.core.multi_market_runner import print_resolved_result

    tick_archive = MultiMarketTickArchive()

    try:
        while True:
            message = await ws.recv()
            data = json.loads(message)

            if data.get("error"):
                print("DERIV ERROR:", data["error"].get("message", data["error"]))
                continue

            tick = data.get("tick")
            if not tick:
                continue

            _RUNTIME_TOTALS["ticks_seen"] += 1

            symbol = tick.get("symbol")
            quote = tick.get("quote")
            epoch = tick.get("epoch")

            if symbol is None or quote is None or epoch is None:
                _RUNTIME_TOTALS["invalid_tick"] += 1
                continue

            symbol = str(symbol)
            health = _health_record(symbol)
            health["ticks_seen"] = int(health.get("ticks_seen") or 0) + 1

            precision, precision_source = resolve_tick_precision(
                symbol,
                tick.get("pip_size"),
            )
            if precision is None:
                _RUNTIME_TOTALS["missing_precision"] += 1
                health["last_rejection"] = "MISSING_PRECISION"
                continue

            if precision_source == "TICK":
                _RUNTIME_TOTALS["tick_precision"] += 1
            elif precision_source == "MARKET_METADATA":
                _RUNTIME_TOTALS["metadata_precision"] += 1

            try:
                epoch = int(epoch)
            except (TypeError, ValueError):
                _RUNTIME_TOTALS["invalid_tick"] += 1
                health["last_rejection"] = "INVALID_EPOCH"
                continue

            previous_tick = latest_ticks.get(symbol)
            if previous_tick is not None and epoch <= previous_tick["epoch"]:
                _RUNTIME_TOTALS["stale_tick"] += 1
                health["last_rejection"] = "STALE_OR_DUPLICATE"
                continue

            digit_result = extract_last_digit_exact(quote, precision)
            if digit_result is None:
                _RUNTIME_TOTALS["format_rejected"] += 1
                health["last_rejection"] = "QUOTE_FORMAT_REJECTED"
                continue

            last_digit, displayed_quote = digit_result

            await asyncio.to_thread(
                tick_archive.add_tick,
                symbol=symbol,
                quote=quote,
                displayed_quote=displayed_quote,
                digit=last_digit,
                epoch=epoch,
                pip_size=precision,
            )

            resolved = learning.resolve(
                symbol,
                last_digit,
                tick_epoch=epoch,
                tick_quote=displayed_quote,
            )
            if resolved is not None:
                print_resolved_result(resolved)

            market_engine.add_tick(symbol, last_digit)

            latest_ticks[symbol] = {
                "epoch": epoch,
                "quote": displayed_quote,
                "displayed_quote": displayed_quote,
                "digit": last_digit,
                "pip_size": precision,
                "precision_source": precision_source,
                "quote_source": "DERIV_OPTIONS_TICK_QUOTE",
                "quote_epoch": epoch,
                "bid": tick.get("bid"),
                "ask": tick.get("ask"),
            }

            _RUNTIME_TOTALS["ticks_accepted"] += 1
            health.update(
                {
                    "ticks_accepted": int(health.get("ticks_accepted") or 0) + 1,
                    "last_epoch": epoch,
                    "last_received_monotonic": time.monotonic(),
                    "last_displayed_quote": displayed_quote,
                    "last_digit": last_digit,
                    "precision": precision,
                    "precision_source": precision_source,
                    "last_rejection": None,
                }
            )

    except websockets.exceptions.ConnectionClosedOK:
        return
    finally:
        tick_archive.close()


def install_precision_runtime(volatility_web_runner_module) -> None:
    if getattr(volatility_web_runner_module, "_dsnpfx_precision_runtime_installed", False):
        return

    original_subscribe = volatility_web_runner_module.subscribe_to_markets

    async def precision_subscribe_to_markets(ws, markets):
        record_market_precisions(markets)
        return await original_subscribe(ws, markets)

    volatility_web_runner_module.subscribe_to_markets = precision_subscribe_to_markets
    volatility_web_runner_module.receive_ticks = precision_receive_ticks
    volatility_web_runner_module._dsnpfx_precision_runtime_installed = True
