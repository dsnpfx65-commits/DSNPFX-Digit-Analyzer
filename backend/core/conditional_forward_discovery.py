"""Prospective conditional/regime discovery for exact next-digit research.

This module does not publish production signals. It records predefined market
conditions at prediction time, resolves only on a strictly later accepted tick,
and keeps discovery and validation partitions separate.

A condition is never called verified merely because its raw accuracy is high.
The validation partition must have enough observations and its 95% Wilson lower
bound must clear the average recorded live DIGITMATCH break-even.
"""

from __future__ import annotations

from datetime import datetime
import json
from math import sqrt
from pathlib import Path
import sqlite3
from threading import RLock

from backend.core.adaptive_forward_ensemble import MODEL_KEYS
from backend.core.proposal_quote_service import get_cached_match_quote


BASELINE_PCT = 10.0
Z_95 = 1.959963984540054
DEFAULT_DATABASE = "backend/data/conditional_forward_discovery.db"
MIN_DISCOVERY = 200
MIN_VALIDATION = 100


def _bucket(value, cuts, labels):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    for cut, label in zip(cuts, labels):
        if number < cut:
            return label
    return labels[-1]


def _valid_digit(value):
    try:
        digit = int(value)
    except (TypeError, ValueError):
        return None
    return digit if 0 <= digit <= 9 else None


def _ready_digit(report):
    if not isinstance(report, dict):
        return None
    if str(report.get("status", "")).upper() != "READY":
        return None
    return _valid_digit(report.get("candidate"))


def _model_candidates(result: dict) -> dict:
    metadata = result.get("model_metadata") or {}
    raw = result.get("raw_model_predictions") or result.get("model_predictions") or {}
    probability = metadata.get("probability_analysis") or {}
    hot = metadata.get("hot_1000_continuation") or {}
    cold = metadata.get("cold_reversion") or {}
    windows = cold.get("windows") or {}
    cold1000 = windows.get(1000) or windows.get("1000") or {}
    return {
        "frequency": _valid_digit(raw.get("frequency")),
        "markov": _valid_digit(raw.get("markov")),
        "sequence": _valid_digit(raw.get("sequence")),
        "probability_best": _valid_digit(probability.get("best_match_digit")),
        "hot_1000": _ready_digit(hot),
        "cold_1000": _ready_digit(cold1000),
    }


def _condition_profiles(result: dict, candidates: dict) -> list[tuple[str, str]]:
    metadata = result.get("model_metadata") or {}
    stats = metadata.get("statistical_deviation") or {}
    seq = metadata.get("sequence") or {}

    regime = str(result.get("regime") or "UNKNOWN").upper()
    entropy = _bucket(
        stats.get("entropy_normalised"),
        (97.0, 98.5, 99.3, 101.0),
        ("LOW", "MID", "HIGH", "VERY_HIGH"),
    )
    deviation = _bucket(
        stats.get("max_abs_z"),
        (1.5, 2.5, 3.5, 1e9),
        ("LOW", "MID", "HIGH", "EXTREME"),
    )
    support = _bucket(
        seq.get("support"),
        (3.0, 6.0, 10.0, 1e9),
        ("LT3", "3_5", "6_9", "10_PLUS"),
    )

    predicted = [digit for digit in candidates.values() if digit is not None]
    if predicted:
        counts = {digit: predicted.count(digit) for digit in set(predicted)}
        agreement_count = max(counts.values())
    else:
        agreement_count = 0
    agreement = (
        "3_PLUS" if agreement_count >= 3 else
        "TWO" if agreement_count == 2 else
        "ONE" if agreement_count == 1 else
        "NONE"
    )

    # These profiles are fixed ahead of outcome resolution. Keeping a small,
    # explicit family of hypotheses limits combinatorial data-mining.
    profiles = [
        ("REGIME", regime),
        ("ENTROPY", entropy),
        ("DEVIATION", deviation),
        ("AGREEMENT", agreement),
        ("REGIME_ENTROPY", f"{regime}|{entropy}"),
        ("REGIME_DEVIATION", f"{regime}|{deviation}"),
        ("REGIME_AGREEMENT", f"{regime}|{agreement}"),
        ("ENTROPY_DEVIATION", f"{entropy}|{deviation}"),
        ("SEQUENCE_SUPPORT", support),
    ]
    return profiles


class ConditionalForwardDiscovery:
    def __init__(self, database: str = DEFAULT_DATABASE):
        self.database = database
        self.lock = RLock()
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        with self.lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conditional_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    symbol TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prediction INTEGER NOT NULL,
                    condition_family TEXT NOT NULL,
                    condition_value TEXT NOT NULL,
                    partition TEXT NOT NULL CHECK(partition IN ('DISCOVERY','VALIDATION')),
                    source_epoch INTEGER NOT NULL,
                    source_quote TEXT NOT NULL,
                    break_even_probability_pct REAL,
                    actual INTEGER,
                    resolved_epoch INTEGER,
                    resolved_quote TEXT,
                    result TEXT CHECK(result IN ('WIN','LOSS'))
                )
                """
            )
            self.connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_conditional_pending
                ON conditional_predictions(
                    symbol, model, condition_family, condition_value
                ) WHERE result IS NULL
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_conditional_stats
                ON conditional_predictions(
                    symbol, model, condition_family, condition_value, partition, result
                )
                """
            )
            self.connection.commit()

    @staticmethod
    def _partition(source_epoch: int) -> str:
        # Deterministic, prospective holdout: 20% validation, 80% discovery.
        return "VALIDATION" if int(source_epoch) % 5 == 0 else "DISCOVERY"

    @staticmethod
    def _wilson(wins: int, total: int):
        if total <= 0:
            return 0.0, 0.0
        p = wins / total
        z2 = Z_95 * Z_95
        denominator = 1.0 + z2 / total
        center = (p + z2 / (2 * total)) / denominator
        margin = Z_95 * sqrt((p * (1 - p) + z2 / (4 * total)) / total) / denominator
        return max(0.0, center - margin) * 100.0, min(1.0, center + margin) * 100.0

    def create_from_result(self, result: dict, source_tick: dict) -> int:
        symbol = str(result.get("symbol") or "")
        if not symbol or not source_tick:
            return 0
        try:
            source_epoch = int(source_tick["epoch"])
        except (KeyError, TypeError, ValueError):
            return 0
        source_quote = source_tick.get("quote")
        candidates = _model_candidates(result)
        profiles = _condition_profiles(result, candidates)
        partition = self._partition(source_epoch)
        saved = 0

        with self.lock:
            for model in MODEL_KEYS:
                digit = candidates.get(model)
                if digit is None:
                    continue
                proposal = get_cached_match_quote(symbol, digit)
                break_even = (
                    proposal.get("break_even_probability_pct")
                    if isinstance(proposal, dict)
                    else None
                )
                try:
                    break_even = float(break_even) if break_even is not None else None
                except (TypeError, ValueError):
                    break_even = None

                for family, value in profiles:
                    pending = self.connection.execute(
                        """
                        SELECT 1 FROM conditional_predictions
                        WHERE symbol=? AND model=? AND condition_family=?
                          AND condition_value=? AND result IS NULL LIMIT 1
                        """,
                        (symbol, model, family, value),
                    ).fetchone()
                    if pending is not None:
                        continue
                    self.connection.execute(
                        """
                        INSERT INTO conditional_predictions(
                            created_at, symbol, model, prediction,
                            condition_family, condition_value, partition,
                            source_epoch, source_quote, break_even_probability_pct
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            datetime.now().isoformat(), symbol, model, digit,
                            family, value, partition, source_epoch,
                            str(source_quote), break_even,
                        ),
                    )
                    saved += 1
            if saved:
                self.connection.commit()
        return saved

    def resolve(self, symbol: str, actual: int, *, tick_epoch: int, tick_quote) -> int:
        actual = _valid_digit(actual)
        if actual is None:
            return 0
        try:
            tick_epoch = int(tick_epoch)
        except (TypeError, ValueError):
            return 0
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT id, prediction FROM conditional_predictions
                WHERE symbol=? AND result IS NULL AND source_epoch < ?
                """,
                (str(symbol), tick_epoch),
            ).fetchall()
            for row in rows:
                outcome = "WIN" if int(row["prediction"]) == actual else "LOSS"
                self.connection.execute(
                    """
                    UPDATE conditional_predictions
                    SET resolved_at=?, actual=?, resolved_epoch=?, resolved_quote=?, result=?
                    WHERE id=?
                    """,
                    (
                        datetime.now().isoformat(), actual, tick_epoch,
                        str(tick_quote), outcome, int(row["id"]),
                    ),
                )
            if rows:
                self.connection.commit()
        return len(rows)

    def _partition_stats(self, symbol, model, family, value, partition):
        with self.lock:
            row = self.connection.execute(
                """
                SELECT COUNT(*) AS n,
                       SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                       AVG(break_even_probability_pct) AS avg_be,
                       COUNT(break_even_probability_pct) AS priced
                FROM conditional_predictions
                WHERE symbol=? AND model=? AND condition_family=?
                  AND condition_value=? AND partition=?
                  AND result IN ('WIN','LOSS')
                """,
                (symbol, model, family, value, partition),
            ).fetchone()
        n = int(row["n"] or 0)
        wins = int(row["wins"] or 0)
        accuracy = wins / n * 100.0 if n else 0.0
        lower, upper = self._wilson(wins, n)
        avg_be = float(row["avg_be"]) if row["avg_be"] is not None else None
        return {
            "resolved": n,
            "wins": wins,
            "losses": n - wins,
            "accuracy_pct": round(accuracy, 4),
            "lower_95_pct": round(lower, 4),
            "upper_95_pct": round(upper, 4),
            "priced_samples": int(row["priced"] or 0),
            "average_break_even_pct": round(avg_be, 4) if avg_be is not None else None,
            "edge_vs_break_even_pp": round(accuracy - avg_be, 4) if avg_be is not None else None,
            "conservative_edge_pp": round(lower - avg_be, 4) if avg_be is not None else None,
        }

    def leaderboard(self, symbol: str | None = None, limit: int = 100) -> list[dict]:
        params = []
        where = "WHERE result IN ('WIN','LOSS')"
        if symbol:
            where += " AND symbol=?"
            params.append(str(symbol))
        with self.lock:
            keys = self.connection.execute(
                f"""
                SELECT DISTINCT symbol, model, condition_family, condition_value
                FROM conditional_predictions {where}
                """,
                params,
            ).fetchall()

        rows = []
        for key in keys:
            sym = str(key["symbol"])
            model = str(key["model"])
            family = str(key["condition_family"])
            value = str(key["condition_value"])
            discovery = self._partition_stats(sym, model, family, value, "DISCOVERY")
            validation = self._partition_stats(sym, model, family, value, "VALIDATION")

            discovery_promising = bool(
                discovery["resolved"] >= MIN_DISCOVERY
                and discovery["lower_95_pct"] > BASELINE_PCT
            )
            validation_economic_edge = bool(
                discovery_promising
                and validation["resolved"] >= MIN_VALIDATION
                and validation["average_break_even_pct"] is not None
                and validation["lower_95_pct"] > validation["average_break_even_pct"]
            )
            if validation_economic_edge:
                status = "VALIDATION EDGE"
            elif discovery_promising:
                status = "VALIDATING"
            elif discovery["resolved"] >= MIN_DISCOVERY:
                status = "NO DISCOVERY EDGE"
            else:
                status = "COLLECTING"

            rows.append({
                "symbol": sym,
                "model": model,
                "condition_family": family,
                "condition_value": value,
                "discovery": discovery,
                "validation": validation,
                "discovery_promising": discovery_promising,
                "validation_economic_edge": validation_economic_edge,
                "status": status,
            })

        rows.sort(
            key=lambda item: (
                bool(item["validation_economic_edge"]),
                float(item["validation"].get("conservative_edge_pp") or -999.0),
                int(item["validation"].get("resolved") or 0),
                float(item["discovery"].get("lower_95_pct") or 0.0),
            ),
            reverse=True,
        )
        return rows[: max(1, int(limit))]

    def summary(self, symbol: str | None = None) -> dict:
        rows = self.leaderboard(symbol=symbol, limit=10000)
        return {
            "scope": "RESEARCH_ONLY_CONDITIONAL_DISCOVERY",
            "baseline_pct": BASELINE_PCT,
            "discovery_minimum": MIN_DISCOVERY,
            "validation_minimum": MIN_VALIDATION,
            "symbol": symbol or "ALL",
            "conditions_tested": len(rows),
            "discovery_promising": sum(bool(row["discovery_promising"]) for row in rows),
            "validation_edges": sum(bool(row["validation_economic_edge"]) for row in rows),
            "leaders": rows,
        }

    def close(self):
        with self.lock:
            self.connection.close()


_INSTANCE = None
_INSTANCE_LOCK = RLock()


def get_conditional_forward_discovery() -> ConditionalForwardDiscovery:
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = ConditionalForwardDiscovery()
        return _INSTANCE
