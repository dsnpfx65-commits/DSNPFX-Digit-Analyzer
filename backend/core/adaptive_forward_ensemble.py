"""Prospective per-market model audit and adaptive research ensemble.

Predictions are recorded before the resolving next tick. Statistical evidence
and trading economics are deliberately separated:

- statistical_eligible: 95% Wilson lower bound clears the 10% digit baseline;
- tradable_eligible: the same lower bound also clears the average live Deriv
  DIGITMATCH break-even recorded for those predictions.

Only tradable-eligible models earn adaptive ensemble weight. This remains
research-only and never bypasses the production evidence gate.
"""

from __future__ import annotations

from datetime import datetime
from math import sqrt
from pathlib import Path
import sqlite3
from threading import RLock

from backend.core.proposal_quote_service import get_cached_match_quote


BASELINE_PCT = 10.0
Z_95 = 1.959963984540054
DEFAULT_DATABASE = "backend/data/adaptive_forward_ensemble.db"

MODEL_KEYS = (
    "frequency",
    "markov",
    "sequence",
    "probability_best",
    "hot_1000",
    "cold_1000",
)


class AdaptiveForwardEnsemble:
    def __init__(self, database: str = DEFAULT_DATABASE):
        self.database = database
        self.lock = RLock()
        path = Path(database)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._create_table()

    def _create_table(self) -> None:
        with self.lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS adaptive_forward_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    symbol TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prediction INTEGER NOT NULL,
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
            columns = {
                row["name"]
                for row in self.connection.execute(
                    "PRAGMA table_info(adaptive_forward_predictions)"
                ).fetchall()
            }
            if "break_even_probability_pct" not in columns:
                self.connection.execute(
                    "ALTER TABLE adaptive_forward_predictions "
                    "ADD COLUMN break_even_probability_pct REAL"
                )
            self.connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_adaptive_pending
                ON adaptive_forward_predictions(symbol, model)
                WHERE result IS NULL
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_adaptive_resolved
                ON adaptive_forward_predictions(symbol, model, result, id DESC)
                """
            )
            self.connection.commit()

    @staticmethod
    def _valid_digit(value):
        try:
            digit = int(value)
        except (TypeError, ValueError):
            return None
        return digit if 0 <= digit <= 9 else None

    @staticmethod
    def _optional_float(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0.0 else None

    @staticmethod
    def _wilson(wins: int, total: int) -> tuple[float, float]:
        if total <= 0:
            return 0.0, 0.0
        p = wins / total
        z2 = Z_95 * Z_95
        denominator = 1.0 + z2 / total
        center = (p + z2 / (2.0 * total)) / denominator
        margin = Z_95 * sqrt(
            (p * (1.0 - p) + z2 / (4.0 * total)) / total
        ) / denominator
        return (
            max(0.0, center - margin) * 100.0,
            min(1.0, center + margin) * 100.0,
        )

    def create_prediction(
        self,
        *,
        symbol: str,
        model: str,
        prediction,
        source_epoch: int,
        source_quote,
        break_even_probability_pct=None,
    ) -> bool:
        model = str(model or "").strip().lower()
        if model not in MODEL_KEYS:
            return False
        digit = self._valid_digit(prediction)
        if digit is None:
            return False
        try:
            source_epoch = int(source_epoch)
        except (TypeError, ValueError):
            return False
        break_even = self._optional_float(break_even_probability_pct)

        with self.lock:
            existing = self.connection.execute(
                """
                SELECT id FROM adaptive_forward_predictions
                WHERE symbol=? AND model=? AND result IS NULL
                LIMIT 1
                """,
                (str(symbol), model),
            ).fetchone()
            if existing is not None:
                return False
            self.connection.execute(
                """
                INSERT INTO adaptive_forward_predictions(
                    created_at, symbol, model, prediction, source_epoch,
                    source_quote, break_even_probability_pct
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    datetime.now().isoformat(),
                    str(symbol),
                    model,
                    digit,
                    source_epoch,
                    str(source_quote),
                    break_even,
                ),
            )
            self.connection.commit()
        return True

    def create_from_result(self, result: dict, source_tick: dict) -> int:
        symbol = result.get("symbol")
        if not symbol or not source_tick:
            return 0

        metadata = result.get("model_metadata") or {}
        models = result.get("raw_model_predictions") or result.get("model_predictions") or {}
        probability = metadata.get("probability_analysis") or {}
        hot = metadata.get("hot_1000_continuation") or {}
        cold = metadata.get("cold_reversion") or {}
        windows = cold.get("windows") or {}
        cold1000 = windows.get(1000) or windows.get("1000") or {}

        candidates = {
            "frequency": models.get("frequency"),
            "markov": models.get("markov"),
            "sequence": models.get("sequence"),
            "probability_best": probability.get("best_match_digit"),
            "hot_1000": (
                hot.get("candidate")
                if str(hot.get("status", "")).upper() == "READY"
                else None
            ),
            "cold_1000": (
                cold1000.get("candidate")
                if str(cold1000.get("status", "")).upper() == "READY"
                else None
            ),
        }

        saved = 0
        for model, prediction in candidates.items():
            digit = self._valid_digit(prediction)
            quote = get_cached_match_quote(symbol, digit) if digit is not None else None
            break_even = (
                quote.get("break_even_probability_pct")
                if isinstance(quote, dict)
                else None
            )
            saved += int(
                self.create_prediction(
                    symbol=symbol,
                    model=model,
                    prediction=digit,
                    source_epoch=source_tick["epoch"],
                    source_quote=source_tick["quote"],
                    break_even_probability_pct=break_even,
                )
            )
        return saved

    def resolve(
        self,
        symbol: str,
        actual: int,
        *,
        tick_epoch: int,
        tick_quote,
    ) -> list[dict]:
        actual_digit = self._valid_digit(actual)
        if actual_digit is None:
            return []
        try:
            tick_epoch = int(tick_epoch)
        except (TypeError, ValueError):
            return []

        with self.lock:
            rows = self.connection.execute(
                """
                SELECT * FROM adaptive_forward_predictions
                WHERE symbol=? AND result IS NULL AND source_epoch < ?
                ORDER BY id ASC
                """,
                (str(symbol), tick_epoch),
            ).fetchall()
            resolved = []
            for row in rows:
                outcome = "WIN" if int(row["prediction"]) == actual_digit else "LOSS"
                self.connection.execute(
                    """
                    UPDATE adaptive_forward_predictions
                    SET resolved_at=?, actual=?, resolved_epoch=?,
                        resolved_quote=?, result=?
                    WHERE id=?
                    """,
                    (
                        datetime.now().isoformat(),
                        actual_digit,
                        tick_epoch,
                        str(tick_quote),
                        outcome,
                        int(row["id"]),
                    ),
                )
                resolved.append(
                    {
                        "id": int(row["id"]),
                        "symbol": str(symbol),
                        "model": str(row["model"]),
                        "prediction": int(row["prediction"]),
                        "actual": actual_digit,
                        "result": outcome,
                    }
                )
            if rows:
                self.connection.commit()
        return resolved

    def statistics(self, symbol: str, model: str, rolling_limit: int = 500) -> dict:
        model = str(model).lower()
        if model not in MODEL_KEYS:
            raise ValueError(f"Unknown model: {model}")
        rolling_limit = max(1, int(rolling_limit))

        with self.lock:
            lifetime = self.connection.execute(
                """
                SELECT
                    COUNT(*) AS resolved,
                    SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) AS wins,
                    COUNT(break_even_probability_pct) AS priced_samples,
                    AVG(break_even_probability_pct) AS average_break_even_pct
                FROM adaptive_forward_predictions
                WHERE symbol=? AND model=? AND result IN ('WIN','LOSS')
                """,
                (str(symbol), model),
            ).fetchone()
            recent_rows = self.connection.execute(
                """
                SELECT result, break_even_probability_pct
                FROM adaptive_forward_predictions
                WHERE symbol=? AND model=? AND result IN ('WIN','LOSS')
                ORDER BY id DESC LIMIT ?
                """,
                (str(symbol), model, rolling_limit),
            ).fetchall()

        resolved = int(lifetime["resolved"] or 0)
        wins = int(lifetime["wins"] or 0)
        accuracy = wins / resolved * 100.0 if resolved else 0.0
        lower, upper = self._wilson(wins, resolved)

        priced_samples = int(lifetime["priced_samples"] or 0)
        average_break_even = self._optional_float(lifetime["average_break_even_pct"])

        recent_n = len(recent_rows)
        recent_wins = sum(row["result"] == "WIN" for row in recent_rows)
        recent_accuracy = recent_wins / recent_n * 100.0 if recent_n else 0.0
        recent_lower, recent_upper = self._wilson(recent_wins, recent_n)
        recent_prices = [
            float(row["break_even_probability_pct"])
            for row in recent_rows
            if row["break_even_probability_pct"] is not None
        ]
        recent_average_break_even = (
            sum(recent_prices) / len(recent_prices) if recent_prices else None
        )

        statistical_eligible = bool(
            resolved >= 100
            and recent_n >= 100
            and lower > BASELINE_PCT
            and recent_lower > BASELINE_PCT
        )

        # Trading eligibility is stricter than statistical significance. We
        # require enough priced observations and both lifetime/recent lower
        # confidence bounds to clear their recorded DIGITMATCH break-even.
        tradable_eligible = bool(
            statistical_eligible
            and priced_samples >= 100
            and len(recent_prices) >= 100
            and average_break_even is not None
            and recent_average_break_even is not None
            and lower > average_break_even
            and recent_lower > recent_average_break_even
        )

        lifetime_edge_vs_break_even = (
            accuracy - average_break_even
            if average_break_even is not None
            else None
        )
        recent_edge_vs_break_even = (
            recent_accuracy - recent_average_break_even
            if recent_average_break_even is not None
            else None
        )

        # Adaptive influence is based only on conservative economic edge.
        if tradable_eligible:
            lifetime_conservative_edge = max(0.0, lower - average_break_even)
            recent_conservative_edge = max(0.0, recent_lower - recent_average_break_even)
            evidence_weight = (
                0.35 * lifetime_conservative_edge
                + 0.65 * recent_conservative_edge
            )
        else:
            evidence_weight = 0.0

        return {
            "symbol": str(symbol),
            "model": model,
            "resolved": resolved,
            "wins": wins,
            "losses": resolved - wins,
            "accuracy_pct": round(accuracy, 4),
            "lower_95_pct": round(lower, 4),
            "upper_95_pct": round(upper, 4),
            "recent_window": rolling_limit,
            "recent_resolved": recent_n,
            "recent_accuracy_pct": round(recent_accuracy, 4),
            "recent_lower_95_pct": round(recent_lower, 4),
            "recent_upper_95_pct": round(recent_upper, 4),
            "baseline_pct": BASELINE_PCT,
            "priced_samples": priced_samples,
            "average_break_even_pct": (
                round(average_break_even, 4)
                if average_break_even is not None
                else None
            ),
            "recent_priced_samples": len(recent_prices),
            "recent_average_break_even_pct": (
                round(recent_average_break_even, 4)
                if recent_average_break_even is not None
                else None
            ),
            "edge_vs_break_even_pp": (
                round(lifetime_edge_vs_break_even, 4)
                if lifetime_edge_vs_break_even is not None
                else None
            ),
            "recent_edge_vs_break_even_pp": (
                round(recent_edge_vs_break_even, 4)
                if recent_edge_vs_break_even is not None
                else None
            ),
            "statistical_eligible": statistical_eligible,
            "tradable_eligible": tradable_eligible,
            # Backward-compatible field now intentionally means tradable.
            "eligible": tradable_eligible,
            "raw_evidence_weight": round(evidence_weight, 6),
        }

    def snapshot(self, symbol: str) -> dict:
        rows = [self.statistics(symbol, model) for model in MODEL_KEYS]
        total = sum(row["raw_evidence_weight"] for row in rows)
        for row in rows:
            row["adaptive_weight_pct"] = (
                round(row["raw_evidence_weight"] / total * 100.0, 2)
                if total > 0
                else 0.0
            )
        return {
            "symbol": str(symbol),
            "scope": "RESEARCH_ONLY_UNTIL_VERIFIED",
            "baseline_pct": BASELINE_PCT,
            "models": rows,
            "statistical_eligible_models": sum(
                bool(row["statistical_eligible"]) for row in rows
            ),
            "tradable_eligible_models": sum(
                bool(row["tradable_eligible"]) for row in rows
            ),
            # Backward-compatible summary now intentionally means tradable.
            "eligible_models": sum(bool(row["tradable_eligible"]) for row in rows),
        }

    def choose(self, symbol: str, candidates: dict) -> dict:
        snapshot = self.snapshot(symbol)
        rows_by_model = {row["model"]: row for row in snapshot["models"]}
        votes: dict[int, float] = {}
        supporters: dict[int, list[str]] = {}

        for model in MODEL_KEYS:
            digit = self._valid_digit(candidates.get(model))
            row = rows_by_model.get(model) or {}
            weight = float(row.get("adaptive_weight_pct", 0.0) or 0.0)
            if (
                digit is None
                or weight <= 0.0
                or not row.get("tradable_eligible")
            ):
                continue
            votes[digit] = votes.get(digit, 0.0) + weight
            supporters.setdefault(digit, []).append(model)

        if not votes:
            return {
                "candidate": None,
                "verified_for_use": False,
                "supporting_models": [],
                "support_count": 0,
                "weight_share_pct": 0.0,
                "snapshot": snapshot,
            }

        winner, winner_weight = max(votes.items(), key=lambda item: item[1])
        total_weight = sum(votes.values())
        support = supporters.get(winner, [])
        share = winner_weight / total_weight * 100.0 if total_weight else 0.0

        # We still require agreement from at least two independently audited
        # tradable-eligible models. One strong model remains research evidence,
        # not an automatic production prediction.
        verified_for_use = len(support) >= 2 and share >= 60.0
        return {
            "candidate": winner if verified_for_use else None,
            "verified_for_use": verified_for_use,
            "supporting_models": support,
            "support_count": len(support),
            "weight_share_pct": round(share, 2),
            "snapshot": snapshot,
        }

    def close(self):
        with self.lock:
            self.connection.close()


_INSTANCE: AdaptiveForwardEnsemble | None = None
_INSTANCE_LOCK = RLock()


def get_adaptive_forward_ensemble() -> AdaptiveForwardEnsemble:
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = AdaptiveForwardEnsemble()
        return _INSTANCE
