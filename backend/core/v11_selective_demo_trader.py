"""V11 selective conditional demo-trading audit.

This module is intentionally paper/demo accounting only. It never sends a buy
request. A trade is committed before settlement only when a conditional rule
has matured in discovery and has enough validation observations to be worth
continued demo evaluation. Actual Deriv DIGITMATCH break-even pricing is stored
with every trade and settlement converts the outcome into a normalized P/L.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from threading import RLock

from backend.core.conditional_forward_discovery import (
    MIN_DISCOVERY,
    get_conditional_forward_discovery,
    _condition_profiles,
    _model_candidates,
)
from backend.core.proposal_quote_service import get_cached_match_quote

DEFAULT_DATABASE = "backend/data/v11_selective_demo.db"
MIN_VALIDATION_TO_TRADE = 50
MIN_DISCOVERY_LOWER_PCT = 10.0


class V11SelectiveDemoTrader:
    def __init__(self, database: str = DEFAULT_DATABASE):
        self.lock = RLock()
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS demo_trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, resolved_at TEXT,
                symbol TEXT NOT NULL, model TEXT NOT NULL,
                condition_family TEXT NOT NULL, condition_value TEXT NOT NULL,
                prediction INTEGER NOT NULL, source_epoch INTEGER NOT NULL,
                source_quote TEXT NOT NULL, break_even_probability_pct REAL NOT NULL,
                ask_price REAL, payout REAL, actual INTEGER, resolved_epoch INTEGER,
                result TEXT CHECK(result IN ('WIN','LOSS')), pnl_units REAL
            )
        """)
        self.connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_v11_pending_symbol
            ON demo_trades(symbol) WHERE result IS NULL
        """)
        self.connection.commit()

    def _eligible_conditions(self, symbol: str):
        audit = get_conditional_forward_discovery()
        rows = audit.leaderboard(symbol=symbol, limit=10000)
        eligible = []
        for row in rows:
            d, v = row["discovery"], row["validation"]
            if d["resolved"] < MIN_DISCOVERY or d["lower_95_pct"] <= MIN_DISCOVERY_LOWER_PCT:
                continue
            if v["resolved"] < MIN_VALIDATION_TO_TRADE:
                continue
            eligible.append(row)
        eligible.sort(key=lambda r: (
            r["validation"]["resolved"],
            r["validation"]["lower_95_pct"],
            r["discovery"]["lower_95_pct"],
        ), reverse=True)
        return eligible

    def consider(self, result: dict, source_tick: dict) -> bool:
        symbol = str(result.get("symbol") or "")
        if not symbol or not source_tick:
            return False
        try:
            epoch = int(source_tick["epoch"])
        except (KeyError, TypeError, ValueError):
            return False
        candidates = _model_candidates(result)
        active_profiles = set(_condition_profiles(result, candidates))
        chosen = None
        for row in self._eligible_conditions(symbol):
            key = (row["condition_family"], row["condition_value"])
            digit = candidates.get(row["model"])
            if key in active_profiles and digit is not None:
                chosen = (row, int(digit))
                break
        if chosen is None:
            return False
        row, digit = chosen
        proposal = get_cached_match_quote(symbol, digit)
        if not isinstance(proposal, dict):
            return False
        try:
            be = float(proposal["break_even_probability_pct"])
        except (KeyError, TypeError, ValueError):
            return False
        ask = proposal.get("ask_price")
        payout = proposal.get("payout")
        try: ask = float(ask) if ask is not None else None
        except (TypeError, ValueError): ask = None
        try: payout = float(payout) if payout is not None else None
        except (TypeError, ValueError): payout = None
        with self.lock:
            pending = self.connection.execute(
                "SELECT 1 FROM demo_trades WHERE symbol=? AND result IS NULL LIMIT 1", (symbol,)
            ).fetchone()
            if pending: return False
            self.connection.execute("""
                INSERT INTO demo_trades(created_at,symbol,model,condition_family,condition_value,
                    prediction,source_epoch,source_quote,break_even_probability_pct,ask_price,payout)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (datetime.now().isoformat(), symbol, row["model"], row["condition_family"],
                  row["condition_value"], digit, epoch, str(source_tick.get("quote")), be, ask, payout))
            self.connection.commit()
        return True

    def resolve(self, symbol: str, actual: int, *, tick_epoch: int, tick_quote=None) -> int:
        try: actual, tick_epoch = int(actual), int(tick_epoch)
        except (TypeError, ValueError): return 0
        if not 0 <= actual <= 9: return 0
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM demo_trades WHERE symbol=? AND result IS NULL AND source_epoch < ?",
                (str(symbol), tick_epoch),
            ).fetchall()
            for row in rows:
                win = int(row["prediction"]) == actual
                be = float(row["break_even_probability_pct"])
                # Unit stake normalized return derived from the quoted break-even.
                pnl = (100.0 / be - 1.0) if win and be > 0 else -1.0
                self.connection.execute("""
                    UPDATE demo_trades SET resolved_at=?,actual=?,resolved_epoch=?,result=?,pnl_units=? WHERE id=?
                """, (datetime.now().isoformat(), actual, tick_epoch, "WIN" if win else "LOSS", pnl, row["id"]))
            if rows: self.connection.commit()
        return len(rows)

    def summary(self):
        with self.lock:
            rows = self.connection.execute("SELECT * FROM demo_trades ORDER BY id DESC").fetchall()
        resolved = [r for r in rows if r["result"] in ("WIN", "LOSS")]
        wins = sum(r["result"] == "WIN" for r in resolved)
        pnl = sum(float(r["pnl_units"] or 0) for r in resolved)
        equity = peak = drawdown = 0.0
        loss_streak = max_loss_streak = 0
        for r in reversed(resolved):
            equity += float(r["pnl_units"] or 0)
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
            if r["result"] == "LOSS":
                loss_streak += 1; max_loss_streak = max(max_loss_streak, loss_streak)
            else: loss_streak = 0
        return {
            "mode": "V11_SELECTIVE_DEMO_PAPER",
            "live_buy_enabled": False,
            "resolved": len(resolved), "pending": len(rows)-len(resolved),
            "wins": wins, "losses": len(resolved)-wins,
            "accuracy_pct": round(wins/len(resolved)*100, 4) if resolved else 0.0,
            "pnl_units": round(pnl, 4),
            "roi_pct_on_unit_stakes": round(pnl/len(resolved)*100, 4) if resolved else 0.0,
            "max_drawdown_units": round(drawdown, 4),
            "max_consecutive_losses": max_loss_streak,
            "minimum_discovery": MIN_DISCOVERY,
            "minimum_validation_to_demo_trade": MIN_VALIDATION_TO_TRADE,
            "recent": [dict(r) for r in rows[:50]],
        }

_INSTANCE = None
_LOCK = RLock()
def get_v11_selective_demo_trader():
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None: _INSTANCE = V11SelectiveDemoTrader()
        return _INSTANCE
