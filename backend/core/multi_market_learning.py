from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import RLock


class MultiMarketLearning:
    """Track one pending next-tick prediction per market."""

    def __init__(
        self,
        model_memory,
        database: str = "backend/data/multi_market_learning.db",
    ):
        self.model_memory = model_memory
        self.database = database
        self.lock = RLock()
        database_path = Path(database)
        database_path.parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    symbol TEXT NOT NULL,
                    predicted INTEGER NOT NULL,
                    actual INTEGER,
                    result TEXT,
                    confidence REAL,
                    edge REAL,
                    edge_grade TEXT,
                    regime TEXT,
                    model_predictions TEXT,
                    model_weights TEXT
                )
                """
            )
            existing_columns = {
                row["name"]
                for row in self.connection.execute(
                    "PRAGMA table_info(predictions)"
                ).fetchall()
            }
            audit_columns = {
                "source_epoch": "INTEGER",
                "source_quote": "TEXT",
                "resolved_epoch": "INTEGER",
                "resolved_quote": "TEXT",
                "selection_mode": "TEXT",
                "market_family": "TEXT",
                "market_quality": "TEXT",

                # V8.3 Phase 3A prospective calibration telemetry.
                # These values describe the evidence available
                # when the prediction was created. They do not
                # participate in live decision making.
                "edge_components": "TEXT",
                "model_statistics": "TEXT",
                "regime_confidence": "REAL",
                "stability_score": "REAL",
                "confidence_margin": "REAL",

                "calibrated_confidence": "REAL",
                "rolling_accuracy": "REAL",
                "rolling_samples": "INTEGER",
                "rolling_lower_bound": "REAL",
                "rolling_upper_bound": "REAL",

                "last20_accuracy": "REAL",
                "last20_samples": "INTEGER",

                "last50_accuracy": "REAL",
                "last50_samples": "INTEGER",
                "last50_upper_bound": "REAL",

                "last100_accuracy": "REAL",
                "last100_samples": "INTEGER",

                "market_qualified": "INTEGER",
                "statistically_above_baseline": "INTEGER",
                "recent_deterioration": "INTEGER",
                "evidence_scope": "TEXT",

                "current_streak_result": "TEXT",
                "current_streak_count": "INTEGER",
            }
            for column, column_type in audit_columns.items():
                if column not in existing_columns:
                    self.connection.execute(
                        f"ALTER TABLE predictions "
                        f"ADD COLUMN {column} {column_type}"
                    )
            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_predictions_pending_symbol
                ON predictions(symbol, result)
                """
            )
            self.connection.commit()

    def has_pending(self, symbol: str) -> bool:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT id
                FROM predictions
                WHERE symbol = ?
                  AND result IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return row is not None

    def create_prediction(self, opportunity: dict) -> bool:
        symbol = opportunity.get("symbol")
        predicted = opportunity.get("prediction")
        if predicted is None:
            predicted = opportunity.get("candidate")
        source_epoch = opportunity.get("source_epoch")
        source_quote = opportunity.get("source_quote")

        if symbol is None or predicted is None or source_epoch is None:
            return False

        with self.lock:
            existing = self.connection.execute(
                """
                SELECT id
                FROM predictions
                WHERE symbol = ?
                  AND result IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if existing is not None:
                return False

            def optional_float(name):
                value = opportunity.get(name)
                if value is None:
                    return None

                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            def optional_int(name):
                value = opportunity.get(name)
                if value is None:
                    return None

                try:
                    return int(value)
                except (TypeError, ValueError):
                    return None

            def optional_bool(name):
                value = opportunity.get(name)
                if value is None:
                    return None

                return int(bool(value))

            telemetry_columns = (
                "created_at",
                "symbol",
                "predicted",
                "confidence",
                "edge",
                "edge_grade",
                "regime",
                "model_predictions",
                "model_weights",
                "source_epoch",
                "source_quote",

                "edge_components",
                "model_statistics",
                "regime_confidence",
                "stability_score",
                "confidence_margin",

                "calibrated_confidence",
                "rolling_accuracy",
                "rolling_samples",
                "rolling_lower_bound",
                "rolling_upper_bound",

                "last20_accuracy",
                "last20_samples",

                "last50_accuracy",
                "last50_samples",
                "last50_upper_bound",

                "last100_accuracy",
                "last100_samples",

                "market_qualified",
                "statistically_above_baseline",
                "recent_deterioration",
                "evidence_scope",

                "current_streak_result",
                "current_streak_count",
            )

            telemetry_values = (
                datetime.now().isoformat(),
                symbol,
                int(predicted),
                float(
                    opportunity.get(
                        "confidence",
                        0,
                    )
                    or 0
                ),
                float(
                    opportunity.get(
                        "edge",
                        0,
                    )
                    or 0
                ),
                str(
                    opportunity.get(
                        "edge_grade",
                        "",
                    )
                ),
                str(
                    opportunity.get(
                        "regime",
                        "UNKNOWN",
                    )
                ),
                json.dumps(
                    opportunity.get(
                        "model_predictions",
                        {},
                    )
                    or {}
                ),
                json.dumps(
                    opportunity.get(
                        "model_weights",
                        {},
                    )
                    or {}
                ),
                int(source_epoch),
                str(source_quote),

                json.dumps(
                    opportunity.get(
                        "edge_components",
                        {},
                    )
                    or {}
                ),
                json.dumps(
                    opportunity.get(
                        "model_statistics",
                        {},
                    )
                    or {}
                ),
                optional_float(
                    "regime_confidence"
                ),
                optional_float(
                    "stability_score"
                ),
                optional_float(
                    "confidence_margin"
                ),

                optional_float(
                    "calibrated_confidence"
                ),
                optional_float(
                    "rolling_accuracy"
                ),
                optional_int(
                    "rolling_samples"
                ),
                optional_float(
                    "rolling_lower_bound"
                ),
                optional_float(
                    "rolling_upper_bound"
                ),

                optional_float(
                    "last20_accuracy"
                ),
                optional_int(
                    "last20_samples"
                ),

                optional_float(
                    "last50_accuracy"
                ),
                optional_int(
                    "last50_samples"
                ),
                optional_float(
                    "last50_upper_bound"
                ),

                optional_float(
                    "last100_accuracy"
                ),
                optional_int(
                    "last100_samples"
                ),

                optional_bool(
                    "market_qualified"
                ),
                optional_bool(
                    "statistically_above_baseline"
                ),
                optional_bool(
                    "recent_deterioration"
                ),

                (
                    str(
                        opportunity.get(
                            "evidence_scope"
                        )
                    )
                    if opportunity.get(
                        "evidence_scope"
                    )
                    is not None
                    else None
                ),

                (
                    str(
                        opportunity.get(
                            "current_streak_result"
                        )
                    )
                    if opportunity.get(
                        "current_streak_result"
                    )
                    is not None
                    else None
                ),

                optional_int(
                    "current_streak_count"
                ),
            )

            if (
                len(telemetry_columns)
                != len(telemetry_values)
            ):
                raise RuntimeError(
                    "Telemetry column/value mismatch"
                )

            placeholders = ", ".join(
                "?"
                for _ in telemetry_columns
            )

            self.connection.execute(
                f"""
                INSERT INTO predictions (
                    {", ".join(telemetry_columns)}
                )
                VALUES ({placeholders})
                """,
                telemetry_values,
            )
            self.connection.commit()
        return True

    @staticmethod
    def _json_object(value) -> dict:
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def resolve(
        self,
        symbol: str,
        actual: int,
        tick_epoch: int,
        tick_quote,
    ) -> dict | None:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT *
                FROM predictions
                WHERE symbol = ?
                  AND result IS NULL
                ORDER BY id ASC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()

            if row is None or row["source_epoch"] is None:
                return None
            if int(tick_epoch) <= int(row["source_epoch"]):
                return None

            predicted = int(row["predicted"])
            result = "WIN" if predicted == int(actual) else "LOSS"
            resolved_at = datetime.now().isoformat()

            self.connection.execute(
                """
                UPDATE predictions
                SET actual = ?,
                    result = ?,
                    resolved_at = ?,
                    resolved_epoch = ?,
                    resolved_quote = ?
                WHERE id = ?
                """,
                (
                    int(actual),
                    result,
                    resolved_at,
                    int(tick_epoch),
                    str(tick_quote),
                    int(row["id"]),
                ),
            )
            self.connection.commit()

        model_predictions = self._json_object(row["model_predictions"])
        model_weights = self._json_object(row["model_weights"])
        model_results = {}

        selection_mode = str(
            row["selection_mode"] or ""
        ).upper()

        research_only = (
            selection_mode == "RESEARCH"
        )

        for model, prediction in model_predictions.items():
            if prediction is None:
                continue

            try:
                saved_weight = float(model_weights.get(model, 0.0) or 0.0)
            except (TypeError, ValueError):
                saved_weight = 0.0

            # Critical V5 rule: a zero-weight model was not active.
            if saved_weight <= 0.0:
                continue

            model_result = (
                "WIN" if int(prediction) == int(actual) else "LOSS"
            )
            if research_only:
                # V8.3 Phase 3A.1:
                # RESEARCH is calibration-only and must never
                # alter adaptive production model memory.
                recorded = False
                record_scope = "RESEARCH_ISOLATED"
            else:
                recorded = self.model_memory.record_result(
                    model,
                    model_result,
                    symbol=symbol,
                    prediction=int(prediction),
                    actual=int(actual),
                    weight=saved_weight,
                    prediction_id=int(row["id"]),
                    selection_mode=row["selection_mode"],
                    created_at=resolved_at,
                )
                record_scope = "TRUSTED_LEARNING"

            model_results[model] = {
                "prediction": int(prediction),
                "result": model_result,
                "weight": saved_weight,
                "recorded": bool(recorded),
                "record_scope": record_scope,
            }

        return {
            "id": int(row["id"]),
            "symbol": symbol,
            "predicted": predicted,
            "actual": int(actual),
            "result": result,
            "edge": float(row["edge"] or 0),
            "confidence": float(row["confidence"] or 0),
            "regime": row["regime"],
            "source_epoch": int(row["source_epoch"]),
            "resolved_epoch": int(tick_epoch),
            "source_quote": row["source_quote"],
            "resolved_quote": str(tick_quote),
            "model_results": model_results,
        }

    def tag_pending_prediction(
        self,
        symbol: str,
        *,
        selection_mode: str,
        market_family: str,
        market_quality: str,
    ) -> bool:
        mode = str(selection_mode or "").upper()
        if mode not in {"PREMIUM", "SHADOW", "RESEARCH"}:
            raise ValueError(f"Invalid selection mode: {selection_mode}")

        with self.lock:
            row = self.connection.execute(
                """
                SELECT id
                FROM predictions
                WHERE symbol = ?
                  AND result IS NULL
                ORDER BY id DESC
                LIMIT 1
                """,
                (str(symbol),),
            ).fetchone()
            if row is None:
                return False

            self.connection.execute(
                """
                UPDATE predictions
                SET selection_mode = ?,
                    market_family = ?,
                    market_quality = ?
                WHERE id = ?
                """,
                (
                    mode,
                    str(market_family or "UNKNOWN"),
                    str(market_quality or "UNKNOWN"),
                    int(row["id"]),
                ),
            )
            self.connection.commit()
        return True

    def honest_statistics(self, rolling_limit: int = 100) -> dict:
        rolling_limit = max(1, int(rolling_limit))

        def summary(where_clause: str, parameters=()):
            with self.lock:
                row = self.connection.execute(
                    f"""
                    SELECT
                        COUNT(*) AS resolved,
                        SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) AS wins,
                        SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) AS losses
                    FROM predictions
                    WHERE result IN ('WIN', 'LOSS')
                      AND ({where_clause})
                    """,
                    parameters,
                ).fetchone()
            resolved = int(row["resolved"] or 0)
            wins = int(row["wins"] or 0)
            losses = int(row["losses"] or 0)
            return {
                "resolved": resolved,
                "wins": wins,
                "losses": losses,
                "accuracy": round(wins / resolved * 100, 2) if resolved else 0.0,
            }

        def rolling_summary(selection_mode: str):
            with self.lock:
                rows = self.connection.execute(
                    """
                    SELECT result
                    FROM predictions
                    WHERE result IN ('WIN', 'LOSS')
                      AND selection_mode = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (selection_mode, rolling_limit),
                ).fetchall()
            resolved = len(rows)
            wins = sum(row["result"] == "WIN" for row in rows)
            return {
                "window": rolling_limit,
                "resolved": resolved,
                "wins": wins,
                "losses": resolved - wins,
                "accuracy": round(wins / resolved * 100, 2) if resolved else 0.0,
            }

        with self.lock:
            pending_row = self.connection.execute(
                "SELECT COUNT(*) AS pending FROM predictions WHERE result IS NULL"
            ).fetchone()

        return {
            "production": summary("selection_mode = 'PREMIUM'"),
            "production_rolling": rolling_summary("PREMIUM"),
            "shadow": summary("selection_mode = 'SHADOW'"),
            "shadow_rolling": rolling_summary("SHADOW"),

            # Calibration-only research evidence.
            "research": summary("selection_mode = 'RESEARCH'"),
            "research_rolling": rolling_summary("RESEARCH"),

            "constrained": summary(
                "market_quality IN ('CONSTRAINED', 'HIGHLY_SKEWED')"
            ),
            "legacy": summary("selection_mode IS NULL OR selection_mode = ''"),
            "pending": int(pending_row["pending"] or 0),
        }

    def statistics(self) -> dict:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN result = 'WIN' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN result = 'LOSS' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN result IS NULL THEN 1 ELSE 0 END) AS pending
                FROM predictions
                """
            ).fetchone()
        total = int(row["total"] or 0)
        wins = int(row["wins"] or 0)
        losses = int(row["losses"] or 0)
        pending = int(row["pending"] or 0)
        resolved = wins + losses
        return {
            "total": total,
            "resolved": resolved,
            "wins": wins,
            "losses": losses,
            "pending": pending,
            "accuracy": round(wins / resolved * 100, 2) if resolved else 0.0,
        }

    def close(self):
        with self.lock:
            self.connection.close()
