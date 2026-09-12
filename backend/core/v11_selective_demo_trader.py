"""V11 selective conditional paper/demo trading audit.

V11 never sends a buy request. It selects only matured conditional setups,
requests a fresh Deriv DIGITMATCH proposal for the exact selected barrier, and
commits the paper trade only while the source tick is still current. Settlement
must occur on a strictly later accepted tick.
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
                ask_price REAL, payout REAL, proposal_id TEXT,
                actual INTEGER, resolved_epoch INTEGER,
                result TEXT CHECK(result IN ('WIN','LOSS')), pnl_units REAL
            )
        """)
        columns = {r[1] for r in self.connection.execute("PRAGMA table_info(demo_trades)").fetchall()}
        if "proposal_id" not in columns:
            self.connection.execute("ALTER TABLE demo_trades ADD COLUMN proposal_id TEXT")
        self.connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_v11_pending_symbol
            ON demo_trades(symbol) WHERE result IS NULL
        """)
        self.connection.commit()

    def _eligible_conditions(self, symbol: str):
        rows = get_conditional_forward_discovery().leaderboard(symbol=symbol, limit=10000)
        eligible = []
        for row in rows:
            discovery, validation = row["discovery"], row["validation"]
            if discovery["resolved"] < MIN_DISCOVERY:
                continue
            if discovery["lower_95_pct"] <= MIN_DISCOVERY_LOWER_PCT:
                continue
            if validation["resolved"] < MIN_VALIDATION_TO_TRADE:
                continue
            eligible.append(row)
        eligible.sort(
            key=lambda row: (
                row["validation"]["resolved"],
                row["validation"]["lower_95_pct"],
                row["discovery"]["lower_95_pct"],
            ),
            reverse=True,
        )
        return eligible

    def has_pending(self, symbol: str) -> bool:
        with self.lock:
            return self.connection.execute(
                "SELECT 1 FROM demo_trades WHERE symbol=? AND result IS NULL LIMIT 1",
                (str(symbol),),
            ).fetchone() is not None

    def select_candidate(self, result: dict, source_tick: dict) -> dict | None:
        """Select a conditional setup before any proposal/outcome is known."""
        symbol = str(result.get("symbol") or "")
        if not symbol or not source_tick or self.has_pending(symbol):
            return None
        try:
            source_epoch = int(source_tick["epoch"])
        except (KeyError, TypeError, ValueError):
            return None

        candidates = _model_candidates(result)
        active_profiles = set(_condition_profiles(result, candidates))
        for row in self._eligible_conditions(symbol):
            key = (row["condition_family"], row["condition_value"])
            digit = candidates.get(row["model"])
            if key not in active_profiles or digit is None:
                continue
            return {
                "symbol": symbol,
                "model": row["model"],
                "condition_family": row["condition_family"],
                "condition_value": row["condition_value"],
                "prediction": int(digit),
                "source_epoch": source_epoch,
                "source_quote": str(source_tick.get("quote")),
                "discovery": row["discovery"],
                "validation": row["validation"],
            }
        return None

    def commit_candidate(self, selection: dict, proposal: dict) -> bool:
        """Commit a selected setup using the fresh exact-barrier proposal."""
        if not isinstance(selection, dict) or not isinstance(proposal, dict):
            return False
        if str(proposal.get("status", "")).upper() != "LIVE":
            return False
        symbol = str(selection.get("symbol") or "")
        try:
            prediction = int(selection["prediction"])
            source_epoch = int(selection["source_epoch"])
            break_even = float(proposal["break_even_probability_pct"])
        except (KeyError, TypeError, ValueError):
            return False
        if str(proposal.get("symbol") or symbol) != symbol:
            return False
        try:
            proposal_digit = int(proposal.get("digit"))
        except (TypeError, ValueError):
            return False
        if proposal_digit != prediction or not 0 <= prediction <= 9 or break_even <= 0:
            return False

        ask, payout = proposal.get("ask_price"), proposal.get("payout")
        try:
            ask = float(ask) if ask is not None else None
            payout = float(payout) if payout is not None else None
        except (TypeError, ValueError):
            return False
        if ask is None or payout is None or ask <= 0 or payout <= 0:
            return False

        with self.lock:
            if self.connection.execute(
                "SELECT 1 FROM demo_trades WHERE symbol=? AND result IS NULL LIMIT 1",
                (symbol,),
            ).fetchone():
                return False
            self.connection.execute("""
                INSERT INTO demo_trades(
                    created_at,symbol,model,condition_family,condition_value,
                    prediction,source_epoch,source_quote,break_even_probability_pct,
                    ask_price,payout,proposal_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                datetime.now().isoformat(), symbol, selection["model"],
                selection["condition_family"], selection["condition_value"], prediction,
                source_epoch, selection["source_quote"], break_even, ask, payout,
                str(proposal.get("proposal_id") or ""),
            ))
            self.connection.commit()
        return True

    def resolve(self, symbol: str, actual: int, *, tick_epoch: int, tick_quote=None) -> int:
        try:
            actual, tick_epoch = int(actual), int(tick_epoch)
        except (TypeError, ValueError):
            return 0
        if not 0 <= actual <= 9:
            return 0
        with self.lock:
            rows = self.connection.execute(
                "SELECT * FROM demo_trades WHERE symbol=? AND result IS NULL AND source_epoch < ?",
                (str(symbol), tick_epoch),
            ).fetchall()
            for row in rows:
                win = int(row["prediction"]) == actual
                ask = float(row["ask_price"])
                payout = float(row["payout"])
                pnl = (payout - ask) / ask if win else -1.0
                self.connection.execute("""
                    UPDATE demo_trades
                    SET resolved_at=?,actual=?,resolved_epoch=?,result=?,pnl_units=?
                    WHERE id=?
                """, (
                    datetime.now().isoformat(), actual, tick_epoch,
                    "WIN" if win else "LOSS", pnl, row["id"],
                ))
            if rows:
                self.connection.commit()
        return len(rows)

    def summary(self):
        with self.lock:
            rows = self.connection.execute("SELECT * FROM demo_trades ORDER BY id DESC").fetchall()
        resolved = [row for row in rows if row["result"] in ("WIN", "LOSS")]
        wins = sum(row["result"] == "WIN" for row in resolved)
        pnl = sum(float(row["pnl_units"] or 0) for row in resolved)
        equity = peak = max_drawdown = 0.0
        loss_streak = max_loss_streak = 0
        for row in reversed(resolved):
            equity += float(row["pnl_units"] or 0)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
            if row["result"] == "LOSS":
                loss_streak += 1
                max_loss_streak = max(max_loss_streak, loss_streak)
            else:
                loss_streak = 0
        return {
            "mode": "V11_SELECTIVE_DEMO_PAPER",
            "live_buy_enabled": False,
            "pricing_mode": "ON_DEMAND_EXACT_BARRIER",
            "resolved": len(resolved),
            "pending": len(rows) - len(resolved),
            "wins": wins,
            "losses": len(resolved) - wins,
            "accuracy_pct": round(wins / len(resolved) * 100, 4) if resolved else 0.0,
            "pnl_units": round(pnl, 4),
            "roi_pct_on_unit_stakes": round(pnl / len(resolved) * 100, 4) if resolved else 0.0,
            "max_drawdown_units": round(max_drawdown, 4),
            "max_consecutive_losses": max_loss_streak,
            "minimum_discovery": MIN_DISCOVERY,
            "minimum_validation_to_demo_trade": MIN_VALIDATION_TO_TRADE,
            "recent": [dict(row) for row in rows[:50]],
        }


_INSTANCE = None
_LOCK = RLock()


def get_v11_selective_demo_trader():
    global _INSTANCE
    with _LOCK:
        if _INSTANCE is None:
            _INSTANCE = V11SelectiveDemoTrader()
        return _INSTANCE
