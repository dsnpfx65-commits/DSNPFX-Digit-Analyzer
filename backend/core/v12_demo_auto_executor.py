"""V12 demo-only Deriv auto-execution controller.

Safety invariants:
- disabled by default;
- demo WebSocket only (real-money URLs are rejected);
- V12 published predictions only;
- exact DIGITMATCH, one tick, exact digit;
- fresh proposal break-even must be below the V12 validation lower bound;
- source tick must still be current before buy;
- one open contract at a time;
- fixed stake, no martingale;
- session loss-streak / stop-loss / take-profit guards.

Credentials are read from environment variables only and are never persisted.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from itertools import count

import websockets

DERIV_API_BASE = "https://api.derivws.com"
DEFAULT_DATABASE = "backend/data/v12_demo_execution.db"
_REQ_IDS = count(900_000)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class DemoExecutionConfig:
    enabled: bool = False
    account_id: str = ""
    auth_token: str = ""
    app_id: str = ""
    stake: float = 0.35
    max_consecutive_losses: int = 3
    session_stop_loss_units: float = 3.0
    session_take_profit_units: float = 5.0
    request_timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls):
        return cls(
            enabled=_env_bool("DSNPFX_AUTO_DEMO_ENABLED", False),
            account_id=os.getenv("DERIV_DEMO_ACCOUNT_ID", "").strip(),
            auth_token=os.getenv("DERIV_AUTH_TOKEN", "").strip(),
            app_id=os.getenv("DERIV_APP_ID", "").strip(),
            stake=float(os.getenv("DSNPFX_DEMO_STAKE", "0.35")),
            max_consecutive_losses=int(os.getenv("DSNPFX_DEMO_MAX_CONSECUTIVE_LOSSES", "3")),
            session_stop_loss_units=float(os.getenv("DSNPFX_DEMO_SESSION_STOP_LOSS_UNITS", "3.0")),
            session_take_profit_units=float(os.getenv("DSNPFX_DEMO_SESSION_TAKE_PROFIT_UNITS", "5.0")),
            request_timeout_seconds=float(os.getenv("DSNPFX_DEMO_REQUEST_TIMEOUT_SECONDS", "5.0")),
        )


class DemoExecutionLedger:
    def __init__(self, database: str = DEFAULT_DATABASE):
        self.lock = RLock()
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS demo_execution_trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                settled_at TEXT,
                symbol TEXT NOT NULL,
                prediction INTEGER NOT NULL,
                source_epoch INTEGER NOT NULL,
                proposal_id TEXT NOT NULL,
                proposal_break_even_pct REAL NOT NULL,
                validation_lower_95_pct REAL NOT NULL,
                stake REAL NOT NULL,
                contract_id TEXT,
                status TEXT NOT NULL,
                result TEXT,
                profit REAL,
                error TEXT
            )
        """)
        self.connection.commit()

    def has_open_trade(self) -> bool:
        with self.lock:
            return self.connection.execute(
                "SELECT 1 FROM demo_execution_trades WHERE status IN ('BUYING','OPEN') LIMIT 1"
            ).fetchone() is not None

    def record_buying(self, *, symbol, prediction, source_epoch, proposal_id,
                      proposal_break_even_pct, validation_lower_95_pct, stake) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            cursor = self.connection.execute("""
                INSERT INTO demo_execution_trades(
                    created_at,symbol,prediction,source_epoch,proposal_id,
                    proposal_break_even_pct,validation_lower_95_pct,stake,status
                ) VALUES(?,?,?,?,?,?,?,?,?)
            """, (now, str(symbol), int(prediction), int(source_epoch), str(proposal_id),
                  float(proposal_break_even_pct), float(validation_lower_95_pct), float(stake), "BUYING"))
            self.connection.commit()
            return int(cursor.lastrowid)

    def mark_open(self, trade_id: int, contract_id) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE demo_execution_trades SET contract_id=?,status='OPEN' WHERE id=?",
                (str(contract_id), int(trade_id)),
            )
            self.connection.commit()

    def mark_rejected(self, trade_id: int, error: str) -> None:
        with self.lock:
            self.connection.execute(
                "UPDATE demo_execution_trades SET status='REJECTED',error=? WHERE id=?",
                (str(error), int(trade_id)),
            )
            self.connection.commit()

    def settle(self, trade_id: int, *, profit: float, result: str) -> None:
        result = str(result).upper()
        if result not in {"WIN", "LOSS"}:
            raise ValueError("result must be WIN or LOSS")
        with self.lock:
            self.connection.execute("""
                UPDATE demo_execution_trades
                SET settled_at=?,status='SETTLED',result=?,profit=?
                WHERE id=?
            """, (datetime.now(timezone.utc).isoformat(), result, float(profit), int(trade_id)))
            self.connection.commit()

    def session_metrics(self) -> dict:
        with self.lock:
            rows = self.connection.execute(
                "SELECT result,profit FROM demo_execution_trades WHERE status='SETTLED' ORDER BY id ASC"
            ).fetchall()
        pnl = sum(float(r["profit"] or 0.0) for r in rows)
        streak = 0
        for row in reversed(rows):
            if row["result"] == "LOSS":
                streak += 1
            else:
                break
        return {"resolved": len(rows), "pnl": pnl, "consecutive_losses": streak}


class DerivDemoTradingClient:
    """Minimal authenticated Deriv Options demo client.

    OTP acquisition uses REST; the returned URL is accepted only when it is the
    demo WebSocket endpoint. This class never connects to /ws/real.
    """

    def __init__(self, config: DemoExecutionConfig):
        self.config = config
        self.websocket = None

    def _request_otp_url_blocking(self) -> str:
        if not self.config.account_id or not self.config.auth_token:
            raise RuntimeError("Demo account ID and auth token are required")
        url = f"{DERIV_API_BASE}/trading/v1/options/accounts/{self.config.account_id}/otp"
        headers = {"Authorization": f"Bearer {self.config.auth_token}"}
        if self.config.app_id:
            headers["Deriv-App-ID"] = self.config.app_id
        req = urllib_request.Request(url, data=b"", method="POST", headers=headers)
        try:
            with urllib_request.urlopen(req, timeout=self.config.request_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Deriv demo OTP request failed: {exc}") from exc
        ws_url = str((payload.get("data") or {}).get("url") or "")
        if "/trading/v1/options/ws/demo" not in ws_url or "/ws/real" in ws_url:
            raise RuntimeError("Deriv returned a non-demo WebSocket URL; execution blocked")
        return ws_url

    async def connect(self):
        if self.websocket is not None:
            return self.websocket
        ws_url = await asyncio.to_thread(self._request_otp_url_blocking)
        self.websocket = await websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=30,
            close_timeout=5,
            max_queue=None,
        )
        return self.websocket

    async def close(self):
        ws, self.websocket = self.websocket, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    async def _request(self, payload: dict, expected_msg_type: str) -> dict:
        ws = await self.connect()
        req_id = next(_REQ_IDS)
        body = dict(payload)
        body["req_id"] = req_id
        await ws.send(json.dumps(body))
        deadline = asyncio.get_running_loop().time() + self.config.request_timeout_seconds
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            data = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            if data.get("req_id") not in (None, req_id):
                continue
            if data.get("error") or data.get("errors"):
                raise RuntimeError(str(data.get("error") or data.get("errors")))
            if data.get("msg_type") == expected_msg_type or expected_msg_type in data:
                return data

    async def buy_proposal(self, proposal_id: str, max_price: float) -> dict:
        data = await self._request(
            {"buy": str(proposal_id), "price": float(max_price)},
            "buy",
        )
        buy = data.get("buy") or {}
        contract_id = buy.get("contract_id")
        if contract_id is None:
            raise RuntimeError("Deriv buy response contained no contract_id")
        return buy

    async def wait_for_settlement(self, contract_id) -> dict:
        ws = await self.connect()
        req_id = next(_REQ_IDS)
        await ws.send(json.dumps({
            "proposal_open_contract": 1,
            "contract_id": contract_id,
            "subscribe": 1,
            "req_id": req_id,
        }))
        deadline = asyncio.get_running_loop().time() + max(15.0, self.config.request_timeout_seconds * 3)
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            data = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            if data.get("error") or data.get("errors"):
                raise RuntimeError(str(data.get("error") or data.get("errors")))
            contract = data.get("proposal_open_contract") or {}
            if str(contract.get("contract_id")) != str(contract_id):
                continue
            if contract.get("is_sold") or str(contract.get("status") or "").lower() in {"won", "lost", "sold"}:
                return contract


class V12DemoAutoExecutor:
    def __init__(self, config: DemoExecutionConfig | None = None,
                 ledger: DemoExecutionLedger | None = None,
                 client: DerivDemoTradingClient | None = None):
        self.config = config or DemoExecutionConfig.from_env()
        self.ledger = ledger or DemoExecutionLedger()
        self.client = client or DerivDemoTradingClient(self.config)
        self.lock = asyncio.Lock()

    def _session_block_reason(self) -> str | None:
        metrics = self.ledger.session_metrics()
        if metrics["consecutive_losses"] >= self.config.max_consecutive_losses:
            return "MAX_CONSECUTIVE_LOSSES"
        if metrics["pnl"] <= -abs(self.config.session_stop_loss_units):
            return "SESSION_STOP_LOSS"
        if metrics["pnl"] >= abs(self.config.session_take_profit_units):
            return "SESSION_TAKE_PROFIT"
        return None

    def validate(self, result: dict, source_tick: dict, current_tick: dict, proposal: dict) -> tuple[bool, str]:
        if not self.config.enabled:
            return False, "AUTO_DEMO_DISABLED"
        if self.ledger.has_open_trade():
            return False, "OPEN_CONTRACT_EXISTS"
        session_reason = self._session_block_reason()
        if session_reason:
            return False, session_reason
        if str(result.get("prediction_source") or "") != "V12_PRECISION_CONDITIONAL_GATE":
            return False, "NOT_V12_PRECISION_SOURCE"
        precision = result.get("precision_decision") or {}
        if not precision.get("verified_for_use"):
            return False, "V12_NOT_VERIFIED"
        prediction = result.get("prediction")
        if prediction is None:
            return False, "NO_PUBLISHED_PREDICTION"
        try:
            prediction = int(prediction)
            source_epoch = int(source_tick["epoch"])
            current_epoch = int(current_tick["epoch"])
            proposal_digit = int(proposal.get("digit"))
            proposal_be = float(proposal["break_even_probability_pct"])
            validation_lower = float(precision["validation_lower_95_pct"])
        except (KeyError, TypeError, ValueError):
            return False, "INVALID_EXECUTION_DATA"
        if not 0 <= prediction <= 9:
            return False, "INVALID_DIGIT"
        if current_epoch != source_epoch:
            return False, "STALE_SOURCE_TICK"
        if str(proposal.get("status") or "").upper() != "LIVE":
            return False, "PROPOSAL_NOT_LIVE"
        if str(proposal.get("contract_type") or "").upper() != "DIGITMATCH":
            return False, "WRONG_CONTRACT_TYPE"
        if proposal_digit != prediction:
            return False, "PROPOSAL_DIGIT_MISMATCH"
        if not proposal.get("proposal_id"):
            return False, "MISSING_PROPOSAL_ID"
        if validation_lower <= proposal_be:
            return False, "FRESH_BREAK_EVEN_NOT_CLEARED"
        if self.config.stake <= 0:
            return False, "INVALID_STAKE"
        return True, "READY"

    async def execute(self, result: dict, source_tick: dict, current_tick: dict, proposal: dict) -> dict:
        async with self.lock:
            ok, reason = self.validate(result, source_tick, current_tick, proposal)
            if not ok:
                return {"executed": False, "reason": reason}
            precision = result["precision_decision"]
            prediction = int(result["prediction"])
            trade_id = self.ledger.record_buying(
                symbol=result.get("symbol"),
                prediction=prediction,
                source_epoch=int(source_tick["epoch"]),
                proposal_id=proposal["proposal_id"],
                proposal_break_even_pct=float(proposal["break_even_probability_pct"]),
                validation_lower_95_pct=float(precision["validation_lower_95_pct"]),
                stake=self.config.stake,
            )
            try:
                # Price is capped at the fixed stake. The proposal itself must
                # have been requested using the same stake before this method.
                buy = await self.client.buy_proposal(proposal["proposal_id"], self.config.stake)
                contract_id = buy["contract_id"]
                self.ledger.mark_open(trade_id, contract_id)
                contract = await self.client.wait_for_settlement(contract_id)
                profit = float(contract.get("profit") or 0.0)
                status = str(contract.get("status") or "").lower()
                result_label = "WIN" if status == "won" or profit > 0 else "LOSS"
                self.ledger.settle(trade_id, profit=profit, result=result_label)
                return {
                    "executed": True,
                    "trade_id": trade_id,
                    "contract_id": contract_id,
                    "result": result_label,
                    "profit": profit,
                }
            except Exception as exc:
                self.ledger.mark_rejected(trade_id, f"{type(exc).__name__}: {exc}")
                await self.client.close()
                return {"executed": False, "reason": "DERIV_EXECUTION_ERROR", "error": str(exc)}


_INSTANCE = None
_INSTANCE_LOCK = RLock()


def get_v12_demo_auto_executor():
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = V12DemoAutoExecutor()
        return _INSTANCE
