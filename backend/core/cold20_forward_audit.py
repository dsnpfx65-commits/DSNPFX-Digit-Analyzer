"""Prospective audit store for the COLD_20_DIFFERS research strategy.

Every prediction is written before its resolving tick. The store is isolated
from production model memory and exists only to measure whether the strategy's
forward DIGITDIFF accuracy clears both the natural 90% baseline and the live
contract break-even probability recorded at prediction time.
"""

from __future__ import annotations

from datetime import datetime
from math import sqrt
from pathlib import Path
import sqlite3
from threading import RLock


Z_95 = 1.959963984540054
DEFAULT_DATABASE = "backend/data/cold20_forward_audit.db"


class Cold20ForwardAudit:
    STRATEGY = "COLD_20_DIFFERS"
    CONTRACT_TYPE = "DIGITDIFF"
    BASELINE_PCT = 90.0

    def __init__(self, database: str = DEFAULT_DATABASE):
        self.database = database
        self.lock = RLock()
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            database,
            timeout=30,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self):
        with self.lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cold20_forward_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    symbol TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    contract_type TEXT NOT NULL,
                    barrier INTEGER NOT NULL,
                    source_epoch INTEGER NOT NULL,
                    source_quote TEXT NOT NULL,
                    resolved_epoch INTEGER,
                    resolved_quote TEXT,
                    actual INTEGER,
                    result TEXT,
                    cold_frequency_pct REAL,
                    historical_differ_rate_pct REAL,
                    break_even_probability_pct REAL,
                    proposal_status TEXT,
                    proposal_ask_price REAL,
                    proposal_payout REAL
                )
                """
            )
            self.connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_cold20_pending_symbol
                ON cold20_forward_predictions(symbol, strategy)
                WHERE result IS NULL
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cold20_resolved_symbol
                ON cold20_forward_predictions(symbol, result, id)
                """
            )
            self.connection.commit()

    @staticmethod
    def _float_or_none(value):
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def create_prediction(
        self,
        *,
        symbol: str,
        barrier: int,
        source_epoch: int,
        source_quote,
        cold_frequency_pct=None,
        historical_differ_rate_pct=None,
        proposal_quote: dict | None = None,
    ) -> bool:
        barrier = int(barrier)
        if not 0 <= barrier <= 9:
            return False

        quote = dict(proposal_quote or {})
        with self.lock:
            existing = self.connection.execute(
                """
                SELECT id
                FROM cold20_forward_predictions
                WHERE symbol = ?
                  AND strategy = ?
                  AND result IS NULL
                LIMIT 1
                """,
                (str(symbol), self.STRATEGY),
            ).fetchone()
            if existing is not None:
                return False

            self.connection.execute(
                """
                INSERT INTO cold20_forward_predictions (
                    created_at,
                    symbol,
                    strategy,
                    contract_type,
                    barrier,
                    source_epoch,
                    source_quote,
                    cold_frequency_pct,
                    historical_differ_rate_pct,
                    break_even_probability_pct,
                    proposal_status,
                    proposal_ask_price,
                    proposal_payout
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    str(symbol),
                    self.STRATEGY,
                    self.CONTRACT_TYPE,
                    barrier,
                    int(source_epoch),
                    str(source_quote),
                    self._float_or_none(cold_frequency_pct),
                    self._float_or_none(historical_differ_rate_pct),
                    self._float_or_none(quote.get("break_even_probability_pct")),
                    str(quote.get("status")) if quote.get("status") is not None else None,
                    self._float_or_none(quote.get("ask_price")),
                    self._float_or_none(quote.get("payout")),
                ),
            )
            self.connection.commit()
        return True

    def resolve(self, symbol: str, actual: int, tick_epoch: int, tick_quote) -> dict | None:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT *
                FROM cold20_forward_predictions
                WHERE symbol = ?
                  AND strategy = ?
                  AND result IS NULL
                ORDER BY id ASC
                LIMIT 1
                """,
                (str(symbol), self.STRATEGY),
            ).fetchone()

            if row is None:
                return None
            if int(tick_epoch) <= int(row["source_epoch"]):
                return None

            actual = int(actual)
            barrier = int(row["barrier"])
            result = "WIN" if actual != barrier else "LOSS"
            resolved_at = datetime.now().isoformat()
            self.connection.execute(
                """
                UPDATE cold20_forward_predictions
                SET resolved_at = ?,
                    resolved_epoch = ?,
                    resolved_quote = ?,
                    actual = ?,
                    result = ?
                WHERE id = ?
                """,
                (
                    resolved_at,
                    int(tick_epoch),
                    str(tick_quote),
                    actual,
                    result,
                    int(row["id"]),
                ),
            )
            self.connection.commit()

        return {
            "id": int(row["id"]),
            "symbol": str(symbol),
            "barrier": barrier,
            "actual": actual,
            "result": result,
            "source_epoch": int(row["source_epoch"]),
            "resolved_epoch": int(tick_epoch),
            "break_even_probability_pct": row["break_even_probability_pct"],
        }

    @staticmethod
    def _wilson_interval(wins: int, total: int) -> tuple[float, float]:
        if total <= 0:
            return 0.0, 0.0
        p = wins / total
        z2 = Z_95 * Z_95
        denominator = 1.0 + z2 / total
        center = (p + z2 / (2.0 * total)) / denominator
        margin = (
            Z_95
            * sqrt((p * (1.0 - p) + z2 / (4.0 * total)) / total)
            / denominator
        )
        return max(0.0, center - margin) * 100.0, min(1.0, center + margin) * 100.0

    def statistics(self, symbol: str | None = None) -> dict:
        where = "result IN ('WIN', 'LOSS')"
        params: tuple = ()
        if symbol is not None:
            where += " AND symbol = ?"
            params = (str(symbol),)

        with self.lock:
            row = self.connection.execute(
                f"""
                SELECT
                    COUNT(*) AS resolved,
                    SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) AS losses,
                    AVG(break_even_probability_pct) AS avg_break_even,
                    COUNT(break_even_probability_pct) AS priced_samples
                FROM cold20_forward_predictions
                WHERE {where}
                """,
                params,
            ).fetchone()
            pending_query = (
                "SELECT COUNT(*) AS pending FROM cold20_forward_predictions "
                "WHERE result IS NULL"
            )
            pending_params: tuple = ()
            if symbol is not None:
                pending_query += " AND symbol = ?"
                pending_params = (str(symbol),)
            pending_row = self.connection.execute(pending_query, pending_params).fetchone()

        resolved = int(row["resolved"] or 0)
        wins = int(row["wins"] or 0)
        losses = int(row["losses"] or 0)
        priced_samples = int(row["priced_samples"] or 0)
        accuracy = wins / resolved * 100.0 if resolved else 0.0
        lower, upper = self._wilson_interval(wins, resolved)
        avg_break_even = self._float_or_none(row["avg_break_even"])
        edge_vs_break_even = (
            accuracy - avg_break_even if avg_break_even is not None else None
        )
        required_level = max(
            self.BASELINE_PCT,
            avg_break_even if avg_break_even is not None else self.BASELINE_PCT,
        )
        verified_edge = bool(resolved >= 100 and lower > required_level)

        return {
            "strategy": self.STRATEGY,
            "contract_type": self.CONTRACT_TYPE,
            "scope": "RESEARCH_ONLY",
            "symbol": str(symbol) if symbol is not None else "ALL",
            "resolved": resolved,
            "wins": wins,
            "losses": losses,
            "pending": int(pending_row["pending"] or 0),
            "accuracy_pct": round(accuracy, 4),
            "lower_95_pct": round(lower, 4),
            "upper_95_pct": round(upper, 4),
            "natural_baseline_pct": self.BASELINE_PCT,
            "priced_samples": priced_samples,
            "average_break_even_pct": (
                round(avg_break_even, 4) if avg_break_even is not None else None
            ),
            "edge_vs_average_break_even_pp": (
                round(edge_vs_break_even, 4)
                if edge_vs_break_even is not None
                else None
            ),
            "verified_edge": verified_edge,
            "decision": "EVIDENCE_EDGE" if verified_edge else "NO_VERIFIED_EDGE",
        }

    def close(self):
        with self.lock:
            self.connection.close()


_AUDIT: Cold20ForwardAudit | None = None
_AUDIT_LOCK = RLock()


def get_cold20_forward_audit() -> Cold20ForwardAudit:
    global _AUDIT
    with _AUDIT_LOCK:
        if _AUDIT is None:
            _AUDIT = Cold20ForwardAudit()
        return _AUDIT


def get_cold20_forward_snapshot(symbol: str | None = None) -> dict:
    return get_cold20_forward_audit().statistics(symbol)
