"""Read-only Deriv digit proposal pricing for DSNPFX research and V11 demo telemetry.

This service requests public DIGITMATCH and DIGITDIFF proposals only. It never
authenticates, never calls buy, and never places a contract.
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

WS_URL="wss://api.derivws.com/trading/v1/options/ws/public"
PROPOSAL_CURRENCY=os.getenv("DERIV_PROPOSAL_CURRENCY","USD").strip() or "USD"
PROPOSAL_STAKE=1.0
PROPOSAL_DURATION=1
PROPOSAL_DURATION_UNIT="t"
REQUEST_TIMEOUT=4.0
REFRESH_SECONDS=12.0
_REQUEST_IDS=count(100_000)
_CACHE={}

def calculate_break_even_probability(ask_price,payout):
    try: ask=float(ask_price); total=float(payout)
    except (TypeError,ValueError): return None
    if ask<=0 or total<=0:return None
    return round(ask/total*100.0,6)

def _cache_key(symbol,contract_type,digit):return str(symbol),str(contract_type).upper(),int(digit)
def get_cached_quote(symbol,contract_type,digit):
    if digit is None:return None
    try:key=_cache_key(symbol,contract_type,digit)
    except (TypeError,ValueError):return None
    quote=_CACHE.get(key)
    return deepcopy(quote) if quote is not None else None
def get_cached_match_quote(symbol,digit):return get_cached_quote(symbol,"DIGITMATCH",digit)
def get_cached_differ_quote(symbol,digit):return get_cached_quote(symbol,"DIGITDIFF",digit)
def _cache_quote(symbol,contract_type,digit,payload):_CACHE[_cache_key(symbol,contract_type,digit)]=deepcopy(payload)

class ProposalQuoteClient:
    def __init__(self):self.websocket=None
    async def _connect(self):
        if self.websocket is not None:return self.websocket
        self.websocket=await websockets.connect(WS_URL,ping_interval=20,ping_timeout=30,close_timeout=5,max_queue=None)
        return self.websocket
    async def close(self):
        ws=self.websocket; self.websocket=None
        if ws is not None:
            try:await ws.close()
            except Exception:pass
    async def request_quote(self,symbol,digit,contract_type):
        symbol=str(symbol); digit=int(digit); contract_type=str(contract_type).upper()
        if not 0<=digit<=9:raise ValueError("Digit barrier must be between 0 and 9")
        if contract_type not in {"DIGITMATCH","DIGITDIFF"}:raise ValueError("Only DIGITMATCH and DIGITDIFF are supported")
        request_id=next(_REQUEST_IDS)
        request={"proposal":1,"amount":PROPOSAL_STAKE,"basis":"stake","contract_type":contract_type,"currency":PROPOSAL_CURRENCY,"duration":PROPOSAL_DURATION,"duration_unit":PROPOSAL_DURATION_UNIT,"barrier":str(digit),"underlying_symbol":symbol,"req_id":request_id}
        try:
            ws=await self._connect(); await ws.send(json.dumps(request)); deadline=asyncio.get_running_loop().time()+REQUEST_TIMEOUT
            while True:
                remaining=deadline-asyncio.get_running_loop().time()
                if remaining<=0:raise asyncio.TimeoutError
                data=json.loads(await asyncio.wait_for(ws.recv(),timeout=remaining)); response_id=data.get("req_id")
                if response_id is not None and int(response_id)!=request_id:continue
                error=data.get("error") or data.get("errors")
                if error:return {"status":"UNAVAILABLE","symbol":symbol,"digit":digit,"contract_type":contract_type,"currency":PROPOSAL_CURRENCY,"error":error,"updated_at":time.time()}
                proposal=data.get("proposal") or {}; ask=proposal.get("ask_price"); payout=proposal.get("payout"); be=calculate_break_even_probability(ask,payout)
                return {"status":"LIVE" if be is not None else "INCOMPLETE","symbol":symbol,"digit":digit,"currency":PROPOSAL_CURRENCY,"basis":"stake","stake":PROPOSAL_STAKE,"duration":PROPOSAL_DURATION,"duration_unit":PROPOSAL_DURATION_UNIT,"contract_type":contract_type,"ask_price":float(ask) if ask is not None else None,"payout":float(payout) if payout is not None else None,"break_even_probability_pct":be,"proposal_id":proposal.get("id"),"spot":proposal.get("spot"),"updated_at":time.time()}
        except (asyncio.TimeoutError,websockets.exceptions.ConnectionClosed):
            await self.close(); return {"status":"UNAVAILABLE","symbol":symbol,"digit":digit,"contract_type":contract_type,"currency":PROPOSAL_CURRENCY,"error":"proposal request timeout/disconnect","updated_at":time.time()}
        except Exception as error:
            await self.close(); return {"status":"UNAVAILABLE","symbol":symbol,"digit":digit,"contract_type":contract_type,"currency":PROPOSAL_CURRENCY,"error":f"{type(error).__name__}: {error}","updated_at":time.time()}
    async def request_match_quote(self,symbol,digit):return await self.request_quote(symbol,digit,"DIGITMATCH")
    async def request_differ_quote(self,symbol,digit):return await self.request_quote(symbol,digit,"DIGITDIFF")

async def request_live_match_quote_once(symbol,digit):
    """Request a fresh exact-barrier MATCH quote for one V11 decision.

    A dedicated short-lived socket avoids waiting for the background cache and
    prevents a stale quote for another barrier from being used as trade evidence.
    """
    client=ProposalQuoteClient()
    try:
        quote=await client.request_match_quote(symbol,digit)
        if isinstance(quote,dict):
            _cache_quote(str(symbol),"DIGITMATCH",int(digit),quote)
        return quote
    finally:
        await client.close()

def _valid_digit(value):
    try:value=int(value)
    except (TypeError,ValueError):return None
    return value if 0<=value<=9 else None

def _research_quote_targets(symbol,market):
    targets=set(); metadata=market.get("model_metadata") or {}
    raw=market.get("raw_model_predictions") or market.get("model_predictions") or {}
    for value in raw.values():
        digit=_valid_digit(value)
        if digit is not None:targets.add((symbol,"DIGITMATCH",digit))
    probability=metadata.get("probability_analysis") or {}; digit=_valid_digit(probability.get("best_match_digit"))
    if digit is None:digit=_valid_digit(market.get("candidate_prediction"))
    if digit is not None:targets.add((symbol,"DIGITMATCH",digit))
    hot=metadata.get("hot_1000_continuation") or {}; digit=_valid_digit(hot.get("candidate"))
    if digit is not None:targets.add((symbol,"DIGITMATCH",digit))
    cold=metadata.get("cold_reversion") or {}; windows=cold.get("windows") or {}
    for window in (200,500,1000):
        report=windows.get(window) or windows.get(str(window)) or {}; digit=_valid_digit(report.get("candidate"))
        if digit is not None:targets.add((symbol,"DIGITMATCH",digit))
    cold20=metadata.get("cold_20_differs") or {}; digit=_valid_digit(cold20.get("candidate"))
    if digit is not None:targets.add((symbol,"DIGITDIFF",digit))
    return targets

async def run_proposal_quote_loop():
    client=ProposalQuoteClient()
    try:
        while True:
            targets=set()
            for symbol,market in get_markets().items():
                if str(market.get("status","")).lower()!="live":continue
                targets.update(_research_quote_targets(str(symbol),market))
            for symbol,contract_type,digit in sorted(targets):
                quote=await client.request_quote(symbol,digit,contract_type); _cache_quote(symbol,contract_type,digit,quote); await asyncio.sleep(0.05)
            await asyncio.sleep(REFRESH_SECONDS)
    except asyncio.CancelledError:raise
    finally:await client.close()
