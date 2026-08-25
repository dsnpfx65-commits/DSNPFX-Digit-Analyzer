"""Dynamic all-Volatility runner for DSNPFX Market Insight.

The validated V8 runner remains the execution core. This wrapper expands the
market universe beyond the legacy ten symbols without guessing that every
Deriv Volatility instrument supports Digits contracts.

Discovery works in two stages:
1. Use Deriv's public Options active_symbols response.
2. Probe known fixed-Volatility symbol candidates for a real public Options tick.

Only symbols that actually return an Options tick are subscribed to the
intelligence engine. Newly discovered symbols stay SHADOW by default; the
existing production accuracy gate is not weakened.
"""

from __future__ import annotations

import asyncio
import json

import websockets

from backend.core.cold20_forward_audit import get_cold20_forward_snapshot
from backend.core.market_discovery import MarketDiscovery
from backend.core import volatility_web_runner as base
from backend.core.multi_market_runner import WS_URL
from backend.core.proposal_quote_service import (
    get_cached_match_quote,
    get_cached_differ_quote,
)
from backend.core.v9_shadow_collector import install as install_v9_shadow_collector
from backend.web_state import publish_state


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


def _number(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _named_market_payload(result, latest_ticks):
    payload = _ORIGINAL_MARKET_PAYLOAD(result, latest_ticks)
    symbol = payload.get("symbol")
    payload["name"] = _MARKET_NAMES.get(symbol, symbol)
    payload["price_source"] = "DERIV_OPTIONS"
    payload["price_source_label"] = "Deriv Options / Digits"

    metadata = dict(payload.get("model_metadata") or {})

    probability = dict(metadata.get("probability_analysis") or {})
    best_digit = probability.get("best_match_digit")
    match_quote = get_cached_match_quote(symbol, best_digit)

    if match_quote is not None:
        break_even = _number(match_quote.get("break_even_probability_pct"))
        estimate = _number(probability.get("best_match_estimate_pct"))
        payout_edge = None
        if break_even is not None and estimate is not None:
            payout_edge = round(estimate - break_even, 4)

        probability["break_even_probability_pct"] = break_even
        probability["estimated_edge_vs_break_even_pp"] = payout_edge
        probability["proposal_quote_status"] = match_quote.get("status")
        probability["proposal_ask_price"] = match_quote.get("ask_price")
        probability["proposal_payout"] = match_quote.get("payout")
        probability["proposal_currency"] = match_quote.get("currency")
        probability["proposal_updated_at"] = match_quote.get("updated_at")

        if (
            probability.get("research_action") == "WATCH"
            and payout_edge is not None
            and payout_edge >= 1.0
            and match_quote.get("status") == "LIVE"
        ):
            probability["payout_action"] = "WATCH"
        else:
            probability["payout_action"] = "NO_TRADE"
    else:
        probability["proposal_quote_status"] = "WAITING"
        probability["payout_action"] = "NO_TRADE"

    cold20 = dict(metadata.get("cold_20_differs") or {})
    cold20_digit = cold20.get("candidate")
    differ_quote = get_cached_differ_quote(symbol, cold20_digit)

    if differ_quote is not None:
        differ_break_even = _number(differ_quote.get("break_even_probability_pct"))
        baseline_edge = None
        if differ_break_even is not None:
            baseline_edge = round(90.0 - differ_break_even, 4)

        cold20["proposal_quote_status"] = differ_quote.get("status")
        cold20["break_even_probability_pct"] = differ_break_even
        cold20["baseline_edge_vs_break_even_pp"] = baseline_edge
        cold20["proposal_ask_price"] = differ_quote.get("ask_price")
        cold20["proposal_payout"] = differ_quote.get("payout")
        cold20["proposal_currency"] = differ_quote.get("currency")
        cold20["proposal_updated_at"] = differ_quote.get("updated_at")
        cold20["payout_action"] = "FORWARD_TEST_ONLY"
    else:
        cold20["proposal_quote_status"] = "WAITING"
        cold20["payout_action"] = "FORWARD_TEST_ONLY"

    # This evidence is generated from records written before their resolving
    # ticks. It is deliberately nested under research metadata and cannot
    # promote a production Match signal.
    forward_evidence = get_cold20_forward_snapshot(symbol)
    cold20["forward_evidence"] = forward_evidence
    cold20["forward_samples"] = forward_evidence.get("resolved", 0)
    cold20["forward_accuracy_pct"] = forward_evidence.get("accuracy_pct", 0.0)
    cold20["forward_lower_95_pct"] = forward_evidence.get("lower_95_pct", 0.0)
    cold20["forward_average_break_even_pct"] = forward_evidence.get(
        "average_break_even_pct"
    )
    cold20["forward_edge_vs_break_even_pp"] = forward_evidence.get(
        "edge_vs_average_break_even_pp"
    )
    cold20["forward_decision"] = forward_evidence.get(
        "decision",
        "NO_VERIFIED_EDGE",
    )

    metadata["probability_analysis"] = probability
    metadata["cold_20_differs"] = cold20
    payload["model_metadata"] = metadata
    payload["proposal_quote"] = match_quote
    payload["differ_proposal_quote"] = differ_quote

    return payload


# Add discovery names, explicit source metadata, read-only proposal pricing and
# prospective COLD20 evidence without changing production evidence logic.
base._market_payload = _named_market_payload

# V9 prospective collectors run beside the production scanner. Existing Match
# shadow learning and isolated COLD20 Differ evidence remain non-trading.
install_v9_shadow_collector(base)


async def _probe_tick_candidates(symbols: set[str]) -> dict[str, dict]:
    """Return candidate metadata only for symbols producing a real Options tick."""
    confirmed: dict[str, dict] = {}

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
            await websocket.send(json.dumps({"ticks": symbol}))

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
                confirmed[symbol] = {
                    "pip_size": tick.get("pip_size"),
                }

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
        print(
            "VOLATILITY SUPPLEMENTAL PROBE ERROR:",
            type(error).__name__,
            error,
        )
        tick_confirmed = {}

    for symbol, tick_meta in tick_confirmed.items():
        merged[symbol] = {
            "symbol": symbol,
            "name": VOLATILITY_CANDIDATES[symbol],
            "type": "VOLATILITY",
            "pip_size": tick_meta.get("pip_size"),
            "discovery_source": "OPTIONS_TICK_PROBE",
        }

    markets = list(merged.values())

    if not markets:
        raise RuntimeError("No live Deriv Options Volatility markets discovered")

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
                        f"Confirmed {len(markets)} live Deriv Options Volatility "
                        "markets. Connecting digit intelligence scanner..."
                    ),
                    "price_source": "DERIV_OPTIONS",
                    "price_source_label": "Deriv Options / Digits",
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
                        "Deriv Options Volatility feed disconnected. "
                        "Rediscovering and re-probing live Digit markets..."
                    ),
                    "price_source": "DERIV_OPTIONS",
                    "price_source_label": "Deriv Options / Digits",
                    "markets_monitoring": sorted(base.VOLATILITY_SYMBOLS),
                    "market_count": len(base.VOLATILITY_SYMBOLS),
                    "decision": "WAIT",
                    "is_premium": False,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            await asyncio.sleep(base.RECONNECT_DELAY)
