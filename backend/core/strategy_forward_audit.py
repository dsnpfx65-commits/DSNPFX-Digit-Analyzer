"""Prospective forward audit for DSNPFX research strategies.

Each record is created before its resolving tick. This database is isolated from
production learning/model memory and exists only to compare research strategies
against their natural baseline and, when available, the live Deriv proposal
break-even captured at prediction time.
"""

from __future__ import annotations

from datetime import datetime
from math import sqrt
from pathlib import Path
import sqlite3
from threading import RLock


Z_95 = 1.959963984540054
DEFAULT_DATABASE = "backend/data/strategy_forward_audit.db"

STRATEGIES = {
    "HOT_1000_MATCH": {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
    "COLD_200_MATCH": {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
    "COLD_500_MATCH": {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
    "COLD_1000_MATCH": {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
    "COLD_20_DIFFERS": {"contract_type": "DIGITDIFF", "baseline_pct": 90.0},
}


class StrategyForwardAudit:
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
                CREATE TABLE IF NOT EXISTS strategy_forward_predictions (
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
                    historical_rate_pct REAL,
                    break_even_probability_pct REAL,
                    proposal_status TEXT,
                    proposal_ask_price REAL,
                    proposal_payout REAL
                )
                """
            )
            self.connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_pending
                ON strategy_forward_predictions(symbol, strategy)
                WHERE result IS NULL
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_resolved
                ON strategy_forward_predictions(strategy, symbol, result, id)
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
        strategy: str,
        barrier: int,
        source_epoch: int,
        source_quote,
        historical_rate_pct=None,
        proposal_quote: dict | None = None,
    ) -> bool:
        strategy = str(strategy).upper()
        config = STRATEGIES.get(strategy)
        if config is None:
            return False

        try:
            barrier = int(barrier)
            source_epoch = int(source_epoch)
        except (TypeError, ValueError):
            return False
        if not 0 <= barrier <= 9:
            return False

        quote = dict(proposal_quote or {})
        with self.lock:
            existing = self.connection.execute(
                """
                SELECT id FROM strategy_forward_predictions
                WHERE symbol = ? AND strategy = ? AND result IS NULL
                LIMIT 1
                """,
                (str(symbol), strategy),
            ).fetchone()
            if existing is not None:
                return False

            self.connection.execute(
                """
                INSERT INTO strategy_forward_predictions (
                    created_at, symbol, strategy, contract_type, barrier,
                    source_epoch, source_quote, historical_rate_pct,
                    break_even_probability_pct, proposal_status,
                    proposal_ask_price, proposal_payout
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    str(symbol),
                    strategy,
                    config["contract_type"],
                    barrier,
                    source_epoch,
                    str(source_quote),
                    self._float_or_none(historical_rate_pct),
                    self._float_or_none(quote.get("break_even_probability_pct")),
                    str(quote.get("status")) if quote.get("status") is not None else None,
                    self._float_or_none(quote.get("ask_price")),
                    self._float_or_none(quote.get("payout")),
                ),
            )
            self.connection.commit()
        return True

    def resolve(self, symbol: str, actual: int, tick_epoch: int, tick_quote) -> list[dict]:
        try:
            actual = int(actual)
            tick_epoch = int(tick_epoch)
        except (TypeError, ValueError):
            return []

        with self.lock:
            rows = self.connection.execute(
                """
                SELECT * FROM strategy_forward_predictions
                WHERE symbol = ? AND result IS NULL AND source_epoch < ?
                ORDER BY id ASC
                """,
                (str(symbol), tick_epoch),
            ).fetchall()

            resolved = []
            for row in rows:
                barrier = int(row["barrier"])
                contract_type = str(row["contract_type"])
                if contract_type == "DIGITMATCH":
                    result = "WIN" if actual == barrier else "LOSS"
                else:
                    result = "WIN" if actual != barrier else "LOSS"

                self.connection.execute(
                    """
                    UPDATE strategy_forward_predictions
                    SET resolved_at = ?, resolved_epoch = ?, resolved_quote = ?,
                        actual = ?, result = ?
                    WHERE id = ?
                    """,
                    (
                        datetime.now().isoformat(),
                        tick_epoch,
                        str(tick_quote),
                        actual,
                        result,
                        int(row["id"]),
                    ),
                )
                resolved.append(
                    {
                        "id": int(row["id"]),
                        "symbol": str(symbol),
                        "strategy": str(row["strategy"]),
                        "contract_type": contract_type,
                        "barrier": barrier,
                        "actual": actual,
                        "result": result,
                        "source_epoch": int(row["source_epoch"]),
                        "resolved_epoch": tick_epoch,
                    }
                )
            if rows:
                self.connection.commit()
        return resolved

    @staticmethod
    def _wilson_interval(wins: int, total: int) -> tuple[float, float]:
        if total <= 0:
            return 0.0, 0.0
        p = wins / total
        z2 = Z_95 * Z_95
        denominator = 1.0 + z2 / total
        center = (p + z2 / (2.0 * total)) / denominator
        margin = Z_95 * sqrt(
            (p * (1.0 - p) + z2 / (4.0 * total)) / total
        ) / denominator
        return max(0.0, center - margin) * 100.0, min(1.0, center + margin) * 100.0

    def statistics(self, strategy: str, symbol: str | None = None) -> dict:
        strategy = str(strategy).upper()
        config = STRATEGIES[strategy]
        where = "strategy = ? AND result IN ('WIN', 'LOSS')"
        params: list = [strategy]
        if symbol is not None:
            where += " AND symbol = ?"
            params.append(str(symbol))

        with self.lock:
            row = self.connection.execute(
                f"""
                SELECT COUNT(*) AS resolved,
                       SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) AS losses,
                       AVG(break_even_probability_pct) AS avg_break_even,
                       COUNT(break_even_probability_pct) AS priced_samples
                FROM strategy_forward_predictions WHERE {where}
                """,
                tuple(params),
            ).fetchone()

            pending_where = "strategy = ? AND result IS NULL"
            pending_params: list = [strategy]
            if symbol is not None:
                pending_where += " AND symbol = ?"
                pending_params.append(str(symbol))
            pending = self.connection.execute(
                f"SELECT COUNT(*) AS pending FROM strategy_forward_predictions WHERE {pending_where}",
                tuple(pending_params),
            ).fetchone()

        resolved = int(row["resolved"] or 0)
        wins = int(row["wins"] or 0)
        losses = int(row["losses"] or 0)
        accuracy = wins / resolved * 100.0 if resolved else 0.0
        lower, upper = self._wilson_interval(wins, resolved)
        avg_break_even = self._float_or_none(row["avg_break_even"])
        baseline = float(config["baseline_pct"])
        required_level = max(baseline, avg_break_even if avg_break_even is not None else baseline)
        verified = bool(resolved >= 100 and lower > required_level)

        return {
            "strategy": strategy,
            "contract_type": config["contract_type"],
            "scope": "RESEARCH_ONLY",
            "symbol": str(symbol) if symbol is not None else "ALL",
            "resolved": resolved,
            "wins": wins,
            "losses": losses,
            "pending": int(pending["pending"] or 0),
            "accuracy_pct": round(accuracy, 4),
            "lower_95_pct": round(lower, 4),
            "upper_95_pct": round(upper, 4),
            "natural_baseline_pct": baseline,
            "priced_samples": int(row["priced_samples"] or 0),
            "average_break_even_pct": round(avg_break_even, 4) if avg_break_even is not None else None,
            "edge_vs_average_break_even_pp": (
                round(accuracy - avg_break_even, 4) if avg_break_even is not None else None
            ),
            "verified_edge": verified,
            "decision": "EVIDENCE_EDGE" if verified else "NO_VERIFIED_EDGE",
        }

    def comparison(self, symbol: str | None = None) -> list[dict]:
        rows = [self.statistics(strategy, symbol) for strategy in STRATEGIES]
        return sorted(
            rows,
            key=lambda item: (
                bool(item["verified_edge"]),
                item["edge_vs_average_break_even_pp"]
                if item["edge_vs_average_break_even_pp"] is not None
                else -999.0,
                item["lower_95_pct"],
                item["resolved"],
            ),
            reverse=True,
        )

    def close(self):
        with self.lock:
            self.connection.close()


_AUDIT: StrategyForwardAudit | None = None
_AUDIT_LOCK = RLock()


def get_strategy_forward_audit() -> StrategyForwardAudit:
    global _AUDIT
    with _AUDIT_LOCK:
        if _AUDIT is None:
            _AUDIT = StrategyForwardAudit()
        return _AUDIT


def get_strategy_forward_snapshot(strategy: str, symbol: str | None = None) -> dict:
    return get_strategy_forward_audit().statistics(strategy, symbol)


def get_strategy_comparison(symbol: str | None = None) -> list[dict]:
    return get_strategy_forward_audit().comparison(symbol)
