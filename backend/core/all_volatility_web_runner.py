"""Dynamic all-Volatility runner for DSNPFX Market Insight.

The legacy V8 runner is kept as the validated execution core. This wrapper
refreshes its monitored symbol set from Deriv active_symbols before every
connection cycle, selecting only markets classified as VOLATILITY.

Newly discovered Volatility symbols are shadow-learning by default. The
existing production accuracy gate remains unchanged, so expanding discovery
does not silently weaken production qualification.
"""

from __future__ import annotations

import asyncio

from backend.core.market_discovery import MarketDiscovery
from backend.core import volatility_web_runner as base
from backend.web_state import publish_state

_MARKET_NAMES: dict[str, str] = {}
_ORIGINAL_MARKET_PAYLOAD = base._market_payload


def _named_market_payload(result, latest_ticks):
    payload = _ORIGINAL_MARKET_PAYLOAD(result, latest_ticks)
    symbol = payload.get("symbol")
    payload["name"] = _MARKET_NAMES.get(symbol, symbol)
    return payload


# Add discovery names to the existing, tested payload without changing its
# evidence or signal logic.
base._market_payload = _named_market_payload


async def _refresh_volatility_universe() -> list[dict]:
    discovery = MarketDiscovery()
    discovered = await discovery.fetch()

    markets = [
        market
        for market in discovered
        if market.get("type") == "VOLATILITY"
        and market.get("symbol")
    ]

    if not markets:
        raise RuntimeError("No active Deriv Volatility markets discovered")

    symbols = {market["symbol"] for market in markets}

    # VOLATILITY_SYMBOLS is intentionally a mutable set in the validated
    # runner. Updating it here makes every downstream filter/subscription use
    # the live Deriv Volatility universe rather than the original fixed 10.
    base.VOLATILITY_SYMBOLS.clear()
    base.VOLATILITY_SYMBOLS.update(symbols)

    _MARKET_NAMES.clear()
    _MARKET_NAMES.update(
        {
            market["symbol"]: (
                market.get("name")
                or market["symbol"]
            )
            for market in markets
        }
    )

    return markets


async def run_forever():
    while True:
        try:
            markets = await _refresh_volatility_universe()
            symbols = sorted(market["symbol"] for market in markets)

            await publish_state(
                {
                    "status": "collecting",
                    "message": (
                        f"Discovered {len(markets)} active Deriv Volatility "
                        "markets. Connecting live scanner..."
                    ),
                    "markets_monitoring": symbols,
                    "market_count": len(markets),
                    "decision": "WAIT",
                    "is_premium": False,
                }
            )

            await base.run_once()

        except asyncio.CancelledError:
            raise

        except Exception as error:
            await publish_state(
                {
                    "status": "reconnecting",
                    "message": (
                        "Volatility feed disconnected. Rediscovering every "
                        "active Deriv Volatility market..."
                    ),
                    "markets_monitoring": sorted(base.VOLATILITY_SYMBOLS),
                    "market_count": len(base.VOLATILITY_SYMBOLS),
                    "decision": "WAIT",
                    "is_premium": False,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            await asyncio.sleep(base.RECONNECT_DELAY)
