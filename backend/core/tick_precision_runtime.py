from __future__ import annotations

import asyncio
import json
from decimal import Decimal, InvalidOperation
from typing import Any

import websockets


_PRECISION_BY_SYMBOL: dict[str, int] = {}


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

    # Integer-like values mean "number of decimal places".
    if decimal_value == decimal_value.to_integral_value():
        integer = int(decimal_value)
        return integer if integer >= 0 else None

    # Fractional values are treated as pip-size increments such as 0.001.
    if Decimal("0") < decimal_value < Decimal("1"):
        normalized = decimal_value.normalize()
        exponent = normalized.as_tuple().exponent
        return max(0, -exponent)

    return None


def record_market_precisions(markets) -> dict[str, int]:
    for market in markets or []:
        symbol = market.get("symbol") if isinstance(market, dict) else None
        if not symbol:
            continue
        precision = normalize_precision(market.get("pip_size"))
        if precision is not None:
            _PRECISION_BY_SYMBOL[str(symbol)] = precision
    return dict(_PRECISION_BY_SYMBOL)


def get_market_precision(symbol: str | None) -> int | None:
    if not symbol:
        return None
    return _PRECISION_BY_SYMBOL.get(str(symbol))


def resolve_tick_precision(symbol: str | None, tick_pip_size: Any) -> tuple[int | None, str]:
    """Resolve precision with tick metadata first and market metadata second."""
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

    # Decimal avoids float representation noise while fixed-point formatting
    # restores settlement-significant trailing zeros.
    return f"{decimal_quote:.{normalized_precision}f}"


def extract_last_digit_exact(quote: Any, precision: Any) -> tuple[int, str] | None:
    displayed_quote = format_quote_exact(quote, precision)
    if displayed_quote is None or not displayed_quote[-1].isdigit():
        return None
    return int(displayed_quote[-1]), displayed_quote


async def precision_receive_ticks(ws, market_engine, learning, latest_ticks):
    """Receive Deriv Options ticks without requiring tick-level pip_size.

    Digit settlement always uses the tick ``quote`` formatted with official
    precision. Bid/ask values, when present, are retained only as diagnostics
    and never participate in Match/Differ digit extraction.
    """
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

            symbol = tick.get("symbol")
            quote = tick.get("quote")
            epoch = tick.get("epoch")

            if symbol is None or quote is None or epoch is None:
                continue

            precision, precision_source = resolve_tick_precision(
                symbol,
                tick.get("pip_size"),
            )
            if precision is None:
                continue

            try:
                epoch = int(epoch)
            except (TypeError, ValueError):
                continue

            previous_tick = latest_ticks.get(symbol)
            if previous_tick is not None and epoch <= previous_tick["epoch"]:
                continue

            digit_result = extract_last_digit_exact(quote, precision)
            if digit_result is None:
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
                # Diagnostics only. These fields never affect the last digit.
                "bid": tick.get("bid"),
                "ask": tick.get("ask"),
            }

    except websockets.exceptions.ConnectionClosedOK:
        return
    finally:
        tick_archive.close()


def install_precision_runtime(volatility_web_runner_module) -> None:
    """Install precision-aware subscription/receive hooks into the web runner."""
    if getattr(volatility_web_runner_module, "_dsnpfx_precision_runtime_installed", False):
        return

    original_subscribe = volatility_web_runner_module.subscribe_to_markets

    async def precision_subscribe_to_markets(ws, markets):
        record_market_precisions(markets)
        return await original_subscribe(ws, markets)

    volatility_web_runner_module.subscribe_to_markets = precision_subscribe_to_markets
    volatility_web_runner_module.receive_ticks = precision_receive_ticks
    volatility_web_runner_module._dsnpfx_precision_runtime_installed = True
