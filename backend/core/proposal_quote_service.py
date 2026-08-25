"""Read-only Deriv digit proposal pricing for DSNPFX research telemetry.

This service requests public DIGITMATCH and DIGITDIFF price proposals only.
It never authenticates, never calls ``buy``, and never places a contract. The
quotes are used only to compare research hypotheses with live break-even rates.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from itertools import count
import json
import os
import time

import websockets

from backend.web_state import get_markets


WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
PROPOSAL_CURRENCY = os.getenv("DERIV_PROPOSAL_CURRENCY", "USD").strip() or "USD"
PROPOSAL_STAKE = 1.0
PROPOSAL_DURATION = 1
PROPOSAL_DURATION_UNIT = "t"
REQUEST_TIMEOUT = 4.0
REFRESH_SECONDS = 12.0

_REQUEST_IDS = count(100_000)
_CACHE: dict[tuple[str, str, int], dict] = {}


def calculate_break_even_probability(ask_price, payout) -> float | None:
    """Return stake/total-payout as a percentage when both values are valid."""
    try:
        ask = float(ask_price)
        total_payout = float(payout)
    except (TypeError, ValueError):
        return None
    if ask <= 0.0 or total_payout <= 0.0:
        return None
    return round(ask / total_payout * 100.0, 6)


def _cache_key(symbol: str, contract_type: str, digit: int):
    return str(symbol), str(contract_type).upper(), int(digit)


def get_cached_quote(symbol: str, contract_type: str, digit: int | None) -> dict | None:
    if digit is None:
        return None
    try:
        key = _cache_key(symbol, contract_type, digit)
    except (TypeError, ValueError):
        return None
    quote = _CACHE.get(key)
    return deepcopy(quote) if quote is not None else None


def get_cached_match_quote(symbol: str, digit: int | None) -> dict | None:
    return get_cached_quote(symbol, "DIGITMATCH", digit)


def get_cached_differ_quote(symbol: str, digit: int | None) -> dict | None:
    return get_cached_quote(symbol, "DIGITDIFF", digit)


def _cache_quote(symbol: str, contract_type: str, digit: int, payload: dict) -> None:
    _CACHE[_cache_key(symbol, contract_type, digit)] = deepcopy(payload)


class ProposalQuoteClient:
    """Persistent client for public one-tick digit proposal snapshots."""

    def __init__(self):
        self.websocket = None

    async def _connect(self):
        if self.websocket is not None:
            return self.websocket
        self.websocket = await websockets.connect(
            WS_URL,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=5,
            max_queue=None,
        )
        return self.websocket

    async def close(self):
        websocket = self.websocket
        self.websocket = None
        if websocket is not None:
            try:
                await websocket.close()
            except Exception:
                pass

    async def request_quote(self, symbol: str, digit: int, contract_type: str) -> dict:
        symbol = str(symbol)
        digit = int(digit)
        contract_type = str(contract_type).upper()
        if not 0 <= digit <= 9:
            raise ValueError("Digit barrier must be between 0 and 9")
        if contract_type not in {"DIGITMATCH", "DIGITDIFF"}:
            raise ValueError("Only DIGITMATCH and DIGITDIFF are supported")

        request_id = next(_REQUEST_IDS)
        request = {
            "proposal": 1,
            "amount": PROPOSAL_STAKE,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": PROPOSAL_CURRENCY,
            "duration": PROPOSAL_DURATION,
            "duration_unit": PROPOSAL_DURATION_UNIT,
            "barrier": str(digit),
            "underlying_symbol": symbol,
            "req_id": request_id,
        }

        try:
            websocket = await self._connect()
            await websocket.send(json.dumps(request))
            deadline = asyncio.get_running_loop().time() + REQUEST_TIMEOUT
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                data = json.loads(raw)
                response_id = data.get("req_id")
                if response_id is not None and int(response_id) != request_id:
                    continue

                error = data.get("error") or data.get("errors")
                if error:
                    return {
                        "status": "UNAVAILABLE",
                        "symbol": symbol,
                        "digit": digit,
                        "contract_type": contract_type,
                        "currency": PROPOSAL_CURRENCY,
                        "error": error,
                        "updated_at": time.time(),
                    }

                proposal = data.get("proposal") or {}
                ask_price = proposal.get("ask_price")
                payout = proposal.get("payout")
                break_even = calculate_break_even_probability(ask_price, payout)
                return {
                    "status": "LIVE" if break_even is not None else "INCOMPLETE",
                    "symbol": symbol,
                    "digit": digit,
                    "currency": PROPOSAL_CURRENCY,
                    "basis": "stake",
                    "stake": PROPOSAL_STAKE,
                    "duration": PROPOSAL_DURATION,
                    "duration_unit": PROPOSAL_DURATION_UNIT,
                    "contract_type": contract_type,
                    "ask_price": float(ask_price) if ask_price is not None else None,
                    "payout": float(payout) if payout is not None else None,
                    "break_even_probability_pct": break_even,
                    "proposal_id": proposal.get("id"),
                    "spot": proposal.get("spot"),
                    "updated_at": time.time(),
                }
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            await self.close()
            return {
                "status": "UNAVAILABLE",
                "symbol": symbol,
                "digit": digit,
                "contract_type": contract_type,
                "currency": PROPOSAL_CURRENCY,
                "error": "proposal request timeout/disconnect",
                "updated_at": time.time(),
            }
        except Exception as error:
            await self.close()
            return {
                "status": "UNAVAILABLE",
                "symbol": symbol,
                "digit": digit,
                "contract_type": contract_type,
                "currency": PROPOSAL_CURRENCY,
                "error": f"{type(error).__name__}: {error}",
                "updated_at": time.time(),
            }

    async def request_match_quote(self, symbol: str, digit: int) -> dict:
        return await self.request_quote(symbol, digit, "DIGITMATCH")

    async def request_differ_quote(self, symbol: str, digit: int) -> dict:
        return await self.request_quote(symbol, digit, "DIGITDIFF")


async def run_proposal_quote_loop() -> None:
    """Refresh research Match and Cold-20 Differ proposal prices."""
    client = ProposalQuoteClient()
    try:
        while True:
            markets = get_markets()
            targets: list[tuple[str, str, int]] = []

            for symbol, market in markets.items():
                if str(market.get("status", "")).lower() != "live":
                    continue

                metadata = market.get("model_metadata") or {}
                probability = metadata.get("probability_analysis") or {}
                match_digit = probability.get("best_match_digit")
                if match_digit is None:
                    match_digit = market.get("candidate_prediction")
                try:
                    if match_digit is not None and 0 <= int(match_digit) <= 9:
                        targets.append((str(symbol), "DIGITMATCH", int(match_digit)))
                except (TypeError, ValueError):
                    pass

                cold20 = metadata.get("cold_20_differs") or {}
                differ_digit = cold20.get("candidate")
                try:
                    if differ_digit is not None and 0 <= int(differ_digit) <= 9:
                        targets.append((str(symbol), "DIGITDIFF", int(differ_digit)))
                except (TypeError, ValueError):
                    pass

            for symbol, contract_type, digit in sorted(set(targets)):
                quote = await client.request_quote(symbol, digit, contract_type)
                _cache_quote(symbol, contract_type, digit, quote)
                await asyncio.sleep(0.05)

            await asyncio.sleep(REFRESH_SECONDS)
    except asyncio.CancelledError:
        raise
    finally:
        await client.close()
