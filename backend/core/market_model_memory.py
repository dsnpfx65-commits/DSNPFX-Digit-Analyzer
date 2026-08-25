"""
DSNPFX Intelligence V5 market-specific adaptive model memory.

This module preserves the legacy aggregate table while adding chronological
model-result history for genuine rolling statistics and adaptive suspension.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Any


DEFAULT_DATABASE = Path("backend/data/market_model_memory.db")


class MarketModelMemory:
    RANDOM_BASELINE = 10.0

    MODELS = (
        "frequency",
        "markov",
        "sequence",
        "transition",
        "momentum",
    )

    ACTIVE_WEIGHT_MODELS = (
        "frequency",
        "markov",
        "sequence",
        "transition",
    )

    def __init__(self, database=DEFAULT_DATABASE):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            self.database,
            timeout=30,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.lock = RLock()
        self.create_table()

    def create_table(self) -> None:
        with self.lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_model_performance (
                    symbol TEXT NOT NULL,
                    model TEXT NOT NULL,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (symbol, model)
                )
                """
            )
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_model_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    prediction_id INTEGER,
                    symbol TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prediction INTEGER,
                    actual INTEGER,
                    result TEXT NOT NULL
                        CHECK (result IN ('WIN', 'LOSS')),
                    weight REAL NOT NULL,
                    selection_mode TEXT
                )
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_model_symbol
                ON market_model_performance(symbol)
                """
            )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_market_results_lookup
                ON market_model_results(symbol, model, id DESC)
                """
            )
            self.connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_market_results_prediction_model
                ON market_model_results(prediction_id, model)
                WHERE prediction_id IS NOT NULL
                """
            )
            self.connection.commit()

    @staticmethod
    def _normalise_symbol(symbol: Any) -> str:
        value = str(symbol or "").strip()
        if not value:
            raise ValueError("A non-empty market symbol is required")
        return value

    @staticmethod
    def _normalise_model(model: Any) -> str:
        value = str(model or "").strip().lower()
        if not value:
            raise ValueError("A non-empty model name is required")
        return value

    def _ensure_record(self, cursor, symbol: str, model: str) -> None:
        cursor.execute(
            """
            INSERT OR IGNORE INTO market_model_performance (
                symbol, model, wins, losses
            )
            VALUES (?, ?, 0, 0)
            """,
            (symbol, model),
        )

    def record_result(
        self,
        model,
        result,
        *,
        symbol,
        prediction: int | None = None,
        actual: int | None = None,
        weight: float = 1.0,
        prediction_id: int | None = None,
        selection_mode: str | None = None,
        created_at: str | None = None,
    ) -> bool:
        """
        Record one genuinely active model outcome.

        Zero/negative-weight models are intentionally ignored. The method
        remains backward-compatible with the previous record_result call.
        """
        symbol = self._normalise_symbol(symbol)
        model = self._normalise_model(model)
        result = str(result).upper()
        numeric_weight = float(weight or 0.0)

        if result not in {"WIN", "LOSS"}:
            raise ValueError(f"Invalid model result: {result}")

        if numeric_weight <= 0.0:
            return False

        timestamp = created_at or datetime.now().isoformat()

        with self.lock:
            cursor = self.connection.cursor()
            self._ensure_record(cursor, symbol, model)

            # Idempotent replay protection when a prediction ID exists.
            if prediction_id is not None:
                existing = cursor.execute(
                    """
                    SELECT id
                    FROM market_model_results
                    WHERE prediction_id = ?
                      AND model = ?
                    """,
                    (int(prediction_id), model),
                ).fetchone()
                if existing is not None:
                    return False

            column = "wins" if result == "WIN" else "losses"
            cursor.execute(
                f"""
                UPDATE market_model_performance
                SET {column} = {column} + 1
                WHERE symbol = ?
                  AND model = ?
                """,
                (symbol, model),
            )

            cursor.execute(
                """
                INSERT INTO market_model_results (
                    created_at,
                    prediction_id,
                    symbol,
                    model,
                    prediction,
                    actual,
                    result,
                    weight,
                    selection_mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    int(prediction_id) if prediction_id is not None else None,
                    symbol,
                    model,
                    int(prediction) if prediction is not None else None,
                    int(actual) if actual is not None else None,
                    result,
                    numeric_weight,
                    str(selection_mode or "").upper() or None,
                ),
            )
            self.connection.commit()

        return True

    def _rolling_summary(
        self,
        symbol: str,
        model: str,
        limit: int,
    ) -> dict[str, float | int]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT result
                FROM market_model_results
                WHERE symbol = ?
                  AND model = ?
                  AND weight > 0
                ORDER BY id DESC
                LIMIT ?
                """,
                (symbol, model, max(1, int(limit))),
            ).fetchall()

        samples = len(rows)
        wins = sum(row["result"] == "WIN" for row in rows)
        accuracy = round(wins / samples * 100.0, 2) if samples else 0.0
        return {
            "samples": samples,
            "wins": wins,
            "losses": samples - wins,
            "accuracy": accuracy,
        }

    def statistics(self, model, *, symbol) -> dict:
        symbol = self._normalise_symbol(symbol)
        model = self._normalise_model(model)

        with self.lock:
            cursor = self.connection.cursor()
            self._ensure_record(cursor, symbol, model)
            row = cursor.execute(
                """
                SELECT wins, losses
                FROM market_model_performance
                WHERE symbol = ?
                  AND model = ?
                """,
                (symbol, model),
            ).fetchone()
            self.connection.commit()

        wins = int(row["wins"] or 0)
        losses = int(row["losses"] or 0)
        samples = wins + losses
        lifetime_accuracy = (
            round(wins / samples * 100.0, 2)
            if samples
            else self.RANDOM_BASELINE
        )

        last20 = self._rolling_summary(symbol, model, 20)
        last50 = self._rolling_summary(symbol, model, 50)
        last100 = self._rolling_summary(symbol, model, 100)
        last500 = self._rolling_summary(symbol, model, 500)

        recent = last100 if last100["samples"] else last50
        status = self._status(
            recent_samples=int(recent["samples"]),
            recent_accuracy=float(recent["accuracy"]),
        )

        return {
            "symbol": symbol,
            "model": model,
            "wins": wins,
            "losses": losses,
            "samples": samples,
            "accuracy": lifetime_accuracy,
            "lifetime_samples": samples,
            "lifetime_accuracy": lifetime_accuracy,
            "last20": last20["accuracy"],
            "last20_samples": last20["samples"],
            "last50": last50["accuracy"],
            "last50_samples": last50["samples"],
            "last100": last100["accuracy"],
            "last100_samples": last100["samples"],
            "last500": last500["accuracy"],
            "last500_samples": last500["samples"],
            "recent_accuracy": recent["accuracy"],
            "recent_samples": recent["samples"],
            "status": status,
            "eligible": status not in {"SUSPENDED"},
        }

    @classmethod
    def _status(cls, *, recent_samples: int, recent_accuracy: float) -> str:
        if recent_samples < 30:
            return "LEARNING"
        threshold = 11.0 if recent_samples >= 100 else 10.0
        if recent_accuracy < threshold:
            return "SUSPENDED"
        if recent_accuracy >= 15.0:
            return "ELITE"
        if recent_accuracy >= 13.0:
            return "STRONG"
        return "ACTIVE"

    def adaptive_weights(self, *, symbol) -> dict[str, float]:
        """
        Produce evidence-weighted influence for one market.

        V8.2 rules:
        - zero chronological evidence = zero influence;
        - suspended models = zero influence;
        - low-sample models receive limited evidence-based exploration;
        - established models use recent/lifetime edge;
        - if nobody earns influence, return all-zero weights.
        """
        symbol = self._normalise_symbol(symbol)
        raw: dict[str, float] = {}

        for model in self.ACTIVE_WEIGHT_MODELS:
            stats = self.statistics(
                model,
                symbol=symbol,
            )

            recent_samples = int(
                stats["recent_samples"]
            )
            recent_accuracy = float(
                stats["recent_accuracy"]
            )
            lifetime_accuracy = float(
                stats["lifetime_accuracy"]
            )
            status = str(
                stats["status"]
            )

            if status == "SUSPENDED":
                raw[model] = 0.0
                continue

            # No verified chronological outcomes means
            # no earned ensemble influence.
            if recent_samples <= 0:
                raw[model] = 0.0
                continue

            if recent_samples < 30:
                sample_ratio = min(
                    1.0,
                    recent_samples / 30.0,
                )

                positive_edge = max(
                    0.0,
                    recent_accuracy
                    - self.RANDOM_BASELINE,
                )

                # Small exploration allowance, explicitly
                # bounded by genuine evidence.
                raw[model] = (
                    0.25 + positive_edge
                ) * sample_ratio

                continue

            recent_ratio = min(
                1.0,
                recent_samples / 100.0,
            )

            blended_accuracy = (
                recent_accuracy
                * (0.7 + 0.2 * recent_ratio)
                + lifetime_accuracy
                * (0.3 - 0.2 * recent_ratio)
            )

            edge = max(
                0.0,
                blended_accuracy
                - self.RANDOM_BASELINE,
            )

            reliability = min(
                1.0,
                recent_samples / 100.0,
            )

            raw[model] = (
                edge * reliability
            )

        total = sum(raw.values())

        if total <= 0.0:
            return {
                model: 0.0
                for model
                in self.ACTIVE_WEIGHT_MODELS
            }

        return {
            model: (
                score / total * 100.0
            )
            for model, score
            in raw.items()
        }

    def reliability(self, model, *, symbol) -> dict:
        stats = self.statistics(model, symbol=symbol)
        recent_samples = int(stats["recent_samples"])
        recent_accuracy = float(stats["recent_accuracy"])
        sample_multiplier = min(1.0, recent_samples / 100.0)
        edge_multiplier = max(
            0.0,
            min(1.0, (recent_accuracy - self.RANDOM_BASELINE) / 5.0),
        )
        return {
            **stats,
            "reliability": round(
                100.0 * sample_multiplier * edge_multiplier,
                2,
            ),
        }

    def symbols(self) -> list[str]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT DISTINCT symbol
                FROM market_model_performance
                ORDER BY symbol
                """
            ).fetchall()
        return [str(row["symbol"]) for row in rows]

    def close(self) -> None:
        with self.lock:
            self.connection.close()
