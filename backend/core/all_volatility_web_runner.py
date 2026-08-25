"""Dynamic all-Volatility runner for DSNPFX Market Insight.

The validated V8 runner remains the execution core. This wrapper expands the
market universe beyond the legacy ten symbols without guessing that every
Deriv Volatility instrument supports Digits contracts.

Discovery works in two stages:
1. Use Deriv's public Options active_symbols response.
2. Probe known fixed-Volatility symbol candidates for a real public tick.

Only symbols that actually return a tick are subscribed to the intelligence
engine. Newly discovered symbols stay SHADOW by default; the existing
production accuracy gate is not weakened.
"""

from __future__ import annotations

import asyncio
import json

import websockets

from backend.core.market_discovery import MarketDiscovery
from backend.core import volatility_web_runner as base
from backend.core.multi_market_runner import WS_URL
from backend.core.v9_shadow_collector import install as install_v9_shadow_collector
from backend.web_state import publish_state


# Current Deriv fixed-Volatility naming families. A symbol is NOT accepted just
# because it appears here: _probe_tick_candidates requires the live Deriv API
to return a real tick before we add it to the scanner.
VOLATILITY_CANDIDATES = {
    "R_5": "Volatility 5",
    "1HZ5V": "Volatility 5 (1s)",
    "R_10": "Volatility 10",
    "1HZ10V": "Volatility 10 (1s)",
    "R_15": "Volatility 15",
    "1HZ15V": "Volatility 15 (1s)",
    "R_25": "Volatility 25",
    "1HZ25V": "Volatility 25 (1s)",
    "R_30": "Volatility 30",
    "1HZ30V": "Volatility 30 (1s)",
    "R_50": "Volatility 50",
    "1HZ50V": "Volatility 50 (1s)",
    "R_75": "Volatility 75",
    "1HZ75V": "Volatility 75 (1s)",
    "R_90": "Volatility 90",
    "1HZ90V": "Volatility 90 (1s)",
    "R_100": "Volatility 100",
    "1HZ100V": "Volatility 100 (1s)",
    "R_150": "Volatility 150",
    "1HZ150V": "Volatility 150 (1s)",
    "R_250": "Volatility 250",
    "1HZ250V": "Volatility 250 (1s)",
}

_PROBE_TIMEOUT = 2.5
_MARKET_NAMES: dict[str, str] = {}
_ORIGINAL_MARKET_PAYLOAD = base._market_payload


def _named_market_payload(result, latest_ticks):
    payload = _ORIGINAL_MARKET_PAYLOAD(result, latest_ticks)
    symbol = payload.get("symbol")
    payload["name"] = _MARKET_NAMES.get(symbol, symbol)
    return payload


# Add discovery names to the existing tested payload without changing its
# evidence or signal logic.
base._market_payload = _named_market_payload

# V9 prospective collector runs beside the production scanner. It creates one
# next-tick SHADOW record per market so model evidence can accumulate in
# parallel, while the existing production publication gate remains unchanged.
install_v9_shadow_collector(base)


async def _probe_tick_candidates(symbols: set[str]) -> set[str]:
    """Return only candidate symbols that produce a real Deriv tick."""
    confirmed: set[str] = set()

    if not symbols:
        return confirmed

    async with websockets.connect(
        WS_URL,
        ping_interval=20,
        ping_timeout=30,
        close_timeout=5,
        max_queue=None,
    ) as websocket:
        for symbol in sorted(symbols):
            await websocket.send(
                json.dumps(
                    {
                        "ticks": symbol,
                        "subscribe": 0,
                    }
                )
            )

            try:
                raw = await asyncio.wait_for(
                    websocket.recv(),
                    timeout=_PROBE_TIMEOUT,
                )
            except asyncio.TimeoutError:
                continue

            try:
                data = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue

            tick = data.get("tick")
            if data.get("error") or not tick:
                continue

            returned_symbol = tick.get("symbol")
            if returned_symbol == symbol:
                confirmed.add(symbol)

    return confirmed


class _MergedVolatilityDiscovery:
    """Frozen per-cycle discovery used by the validated base runner."""

    def __init__(self, markets: list[dict]):
        self._markets = [dict(market) for market in markets]

    async def fetch(self):
        return [dict(market) for market in self._markets]


async def _refresh_volatility_universe() -> list[dict]:
    discovery = MarketDiscovery()
    discovered = await discovery.fetch()

    options_markets = [
        market
        for market in discovered
        if market.get("type") == "VOLATILITY"
        and market.get("symbol")
    ]

    merged: dict[str, dict] = {
        market["symbol"]: dict(market)
        for market in options_markets
    }

    missing_candidates = set(VOLATILITY_CANDIDATES) - set(merged)

    try:
        tick_confirmed = await _probe_tick_candidates(missing_candidates)
    except Exception as error:
        # The primary active_symbols universe remains usable if the supplemental
        # probe is temporarily unavailable.
        print(
            "VOLATILITY SUPPLEMENTAL PROBE ERROR:",
            type(error).__name__,
            error,
        )
        tick_confirmed = set()

    for symbol in tick_confirmed:
        merged[symbol] = {
            "symbol": symbol,
            "name": VOLATILITY_CANDIDATES[symbol],
            "type": "VOLATILITY",
            "discovery_source": "TICK_PROBE",
        }

    markets = list(merged.values())

    if not markets:
        raise RuntimeError("No live Deriv Volatility markets discovered")

    symbols = set(merged)

    base.VOLATILITY_SYMBOLS.clear()
    base.VOLATILITY_SYMBOLS.update(symbols)

    _MARKET_NAMES.clear()
    _MARKET_NAMES.update(
        {
            symbol: (
                market.get("name")
                or VOLATILITY_CANDIDATES.get(symbol)
                or symbol
            )
            for symbol, market in merged.items()
        }
    )

    # base.run_once performs its own MarketDiscovery pass and requires every
    # monitored symbol to be returned. Freeze this verified merged universe for
    # that cycle rather than falling back to the legacy 10-symbol response.
    frozen = _MergedVolatilityDiscovery(markets)

    class CycleDiscovery:
        async def fetch(self):
            return await frozen.fetch()

    base.MarketDiscovery = CycleDiscovery

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
                        f"Confirmed {len(markets)} live Deriv Volatility "
                        "markets. Connecting intelligence scanner..."
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
                        "Volatility feed disconnected. Rediscovering and "
                        "re-probing live Deriv Volatility markets..."
                    ),
                    "markets_monitoring": sorted(base.VOLATILITY_SYMBOLS),
                    "market_count": len(base.VOLATILITY_SYMBOLS),
                    "decision": "WAIT",
                    "is_premium": False,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            await asyncio.sleep(base.RECONNECT_DELAY)
