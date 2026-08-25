"""
DSNPFX Production Accuracy Gate V1

A raw candidate or high internal confidence is not enough.
A digit becomes a production signal only when historical,
market-specific evidence demonstrates an edge above the
10% exact-digit random baseline.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import math
import sqlite3


DEFAULT_DATABASE = Path(
    "backend/data/multi_market_learning.db"
)


class ProductionAccuracyGate:
    RANDOM_BASELINE = 10.0

    # One-sided 95% normal quantile.
    # Qualification requires evidence that the underlying
    # exact-digit hit rate exceeds the 10% random baseline.
    QUALIFICATION_Z = 1.6448536269514722

    STANDARD_MARKETS = {
        "R_10",
        "R_25",
        "R_50",
        "R_75",
        "R_100",
    }

    def __init__(
        self,
        database=DEFAULT_DATABASE,
        *,
        minimum_samples=100,
        rolling_window=100,
        minimum_rolling_accuracy=15.0,
        minimum_edge=70.0,
        minimum_raw_confidence=66.0,
        minimum_agreeing_models=2,
    ):
        self.database = Path(database)
        self.minimum_samples = int(
            minimum_samples
        )
        self.rolling_window = int(
            rolling_window
        )
        self.minimum_rolling_accuracy = float(
            minimum_rolling_accuracy
        )
        self.minimum_edge = float(
            minimum_edge
        )
        self.minimum_raw_confidence = float(
            minimum_raw_confidence
        )
        self.minimum_agreeing_models = int(
            minimum_agreeing_models
        )

        if self.minimum_samples < 1:
            raise ValueError(
                "minimum_samples must be positive"
            )

        if self.rolling_window < 1:
            raise ValueError(
                "rolling_window must be positive"
            )

    def _connect(self):
        connection = sqlite3.connect(
            self.database
        )
        connection.row_factory = sqlite3.Row
        return connection

    @classmethod
    def _wilson_bounds(
        cls,
        wins: int,
        samples: int,
        *,
        z: float | None = None,
    ) -> tuple[float, float]:
        """
        Return Wilson score bounds as percentages.

        Qualification uses statistical evidence rather than
        treating a raw observed hit rate as certainty.
        """
        samples = int(samples)
        wins = int(wins)

        if samples <= 0:
            return 0.0, 100.0

        z = float(
            cls.QUALIFICATION_Z
            if z is None
            else z
        )

        p = wins / samples
        z2 = z * z

        denominator = (
            1.0
            + z2 / samples
        )

        centre = (
            p
            + z2 / (2.0 * samples)
        ) / denominator

        margin = (
            z
            * math.sqrt(
                (
                    p * (1.0 - p)
                    + z2 / (4.0 * samples)
                )
                / samples
            )
            / denominator
        )

        lower = max(
            0.0,
            (centre - margin) * 100.0,
        )

        upper = min(
            100.0,
            (centre + margin) * 100.0,
        )

        return (
            round(lower, 4),
            round(upper, 4),
        )

    @staticmethod
    def _result_summary(rows) -> dict:
        samples = len(rows)

        wins = sum(
            row["result"] == "WIN"
            for row in rows
        )

        accuracy = (
            wins / samples * 100.0
            if samples
            else 0.0
        )

        return {
            "samples": samples,
            "wins": wins,
            "losses": samples - wins,
            "accuracy": round(
                accuracy,
                2,
            ),
        }

    @staticmethod
    def _current_streak(rows) -> dict:
        if not rows:
            return {
                "result": None,
                "count": 0,
            }

        current = rows[-1]["result"]
        count = 0

        for row in reversed(rows):
            if row["result"] != current:
                break
            count += 1

        return {
            "result": current,
            "count": count,
        }

    def market_statistics(
        self,
        symbol: str,
    ) -> dict:
        """
        Calculate symbol-specific lifetime and rolling results.

        Historical records are preserved. These statistics use
        only next-tick records already marked WIN or LOSS.
        """

        with self._connect() as connection:
            lifetime = connection.execute(
                """
                SELECT result
                FROM predictions
                WHERE symbol = ?
                  AND result IN ('WIN', 'LOSS')
                  AND selection_mode IN ('SHADOW', 'PREMIUM')
                ORDER BY id
                """,
                (symbol,),
            ).fetchall()

            recent = connection.execute(
                """
                SELECT result
                FROM predictions
                WHERE symbol = ?
                  AND result IN ('WIN', 'LOSS')
                  AND selection_mode IN ('SHADOW', 'PREMIUM')
                ORDER BY id DESC
                LIMIT ?
                """,
                (
                    symbol,
                    self.rolling_window,
                ),
            ).fetchall()

        last20 = self._result_summary(
            lifetime[-20:]
        )

        last50 = self._result_summary(
            lifetime[-50:]
        )

        last100 = self._result_summary(
            lifetime[-100:]
        )

        current_streak = self._current_streak(
            lifetime
        )

        lifetime_samples = len(lifetime)
        lifetime_wins = sum(
            row["result"] == "WIN"
            for row in lifetime
        )

        recent_samples = len(recent)
        recent_wins = sum(
            row["result"] == "WIN"
            for row in recent
        )

        lifetime_accuracy = (
            round(
                lifetime_wins
                / lifetime_samples
                * 100,
                2,
            )
            if lifetime_samples
            else 0.0
        )

        rolling_accuracy = (
            round(
                recent_wins
                / recent_samples
                * 100,
                2,
            )
            if recent_samples
            else 0.0
        )

        rolling_lower, rolling_upper = (
            self._wilson_bounds(
                recent_wins,
                recent_samples,
            )
        )

        last50_lower, last50_upper = (
            self._wilson_bounds(
                last50["wins"],
                last50["samples"],
            )
        )

        statistically_above_baseline = (
            recent_samples
            >= self.minimum_samples
            and rolling_lower
            > self.RANDOM_BASELINE
        )

        # A deterioration suspension requires a complete
        # trusted 50-result window whose upper confidence
        # bound is itself below random chance.
        recent_deterioration = (
            last50["samples"] >= 50
            and last50_upper
            < self.RANDOM_BASELINE
        )

        return {
            "symbol": symbol,
            "evidence_scope": "TRUSTED_SHADOW_PREMIUM",
            "lifetime_samples": (
                lifetime_samples
            ),
            "lifetime_wins": lifetime_wins,
            "lifetime_losses": (
                lifetime_samples
                - lifetime_wins
            ),
            "lifetime_accuracy": (
                lifetime_accuracy
            ),
            "rolling_window": (
                self.rolling_window
            ),
            "rolling_samples": recent_samples,
            "rolling_wins": recent_wins,
            "rolling_losses": (
                recent_samples
                - recent_wins
            ),
            "rolling_accuracy": (
                rolling_accuracy
            ),
            # The calibrated confidence is evidence-based:
            # the market's actual rolling win rate.
            "calibrated_confidence": (
                rolling_accuracy
            ),

            "rolling_lower_bound": (
                rolling_lower
            ),
            "rolling_upper_bound": (
                rolling_upper
            ),

            "last20_samples": (
                last20["samples"]
            ),
            "last20_wins": (
                last20["wins"]
            ),
            "last20_accuracy": (
                last20["accuracy"]
            ),

            "last50_samples": (
                last50["samples"]
            ),
            "last50_wins": (
                last50["wins"]
            ),
            "last50_accuracy": (
                last50["accuracy"]
            ),
            "last50_lower_bound": (
                last50_lower
            ),
            "last50_upper_bound": (
                last50_upper
            ),

            "last100_samples": (
                last100["samples"]
            ),
            "last100_wins": (
                last100["wins"]
            ),
            "last100_accuracy": (
                last100["accuracy"]
            ),

            "current_streak_result": (
                current_streak["result"]
            ),
            "current_streak_count": (
                current_streak["count"]
            ),

            "statistically_above_baseline": (
                statistically_above_baseline
            ),

            "recent_deterioration": (
                recent_deterioration
            ),
        }

    @staticmethod
    def model_agreement(
        candidate,
        predictions,
    ) -> dict:
        valid = {
            model: prediction
            for model, prediction
            in (predictions or {}).items()
            if prediction is not None
        }

        counts = Counter(valid.values())

        agreeing_models = [
            model
            for model, prediction
            in valid.items()
            if prediction == candidate
        ]

        return {
            "active_models": len(valid),
            "agreeing_models": (
                len(agreeing_models)
            ),
            "agreeing_model_names": (
                agreeing_models
            ),
            "vote_counts": dict(counts),
        }

    def evaluate(
        self,
        market: dict,
    ) -> dict:
        symbol = str(
            market.get("symbol") or ""
        )

        candidate = market.get(
            "candidate_prediction"
        )

        raw_confidence = float(
            market.get("confidence") or 0
        )

        edge_score = float(
            market.get("edge_score") or 0
        )

        statistics = self.market_statistics(
            symbol
        )

        agreement = self.model_agreement(
            candidate,
            market.get(
                "model_predictions",
                {},
            ),
        )

        reasons = []

        if symbol not in self.STANDARD_MARKETS:
            reasons.append(
                "Market is not production-approved"
            )

        if (
            market.get("market_quality")
            != "TEN_DIGIT"
        ):
            reasons.append(
                "Market quality is not TEN_DIGIT"
            )

        if candidate is None:
            reasons.append(
                "No candidate digit available"
            )

        if not market.get("raw_premium"):
            reasons.append(
                "Raw Premium Gate did not approve"
            )

        if (
            statistics["rolling_samples"]
            < self.minimum_samples
        ):
            reasons.append(
                "Insufficient rolling samples: "
                f"{statistics['rolling_samples']}/"
                f"{self.minimum_samples}"
            )

        if (
            statistics["rolling_accuracy"]
            < self.minimum_rolling_accuracy
        ):
            reasons.append(
                "Rolling accuracy below "
                f"{self.minimum_rolling_accuracy}%: "
                f"{statistics['rolling_accuracy']}%"
            )

        if (
            statistics["rolling_samples"]
            >= self.minimum_samples
            and not statistics[
                "statistically_above_baseline"
            ]
        ):
            reasons.append(
                "Trusted accuracy is not statistically "
                "verified above the 10% random baseline: "
                f"95% lower bound "
                f"{statistics['rolling_lower_bound']:.2f}%"
            )

        if statistics["recent_deterioration"]:
            reasons.append(
                "Recent trusted performance is "
                "statistically below the 10% baseline: "
                f"last50 "
                f"{statistics['last50_accuracy']:.2f}% "
                f"(95% upper bound "
                f"{statistics['last50_upper_bound']:.2f}%)"
            )

        if edge_score < self.minimum_edge:
            reasons.append(
                "Edge Score below "
                f"{self.minimum_edge}: "
                f"{edge_score}"
            )

        if (
            raw_confidence
            < self.minimum_raw_confidence
        ):
            reasons.append(
                "Raw confidence below "
                f"{self.minimum_raw_confidence}%: "
                f"{raw_confidence}%"
            )

        if (
            agreement["agreeing_models"]
            < self.minimum_agreeing_models
        ):
            reasons.append(
                "Insufficient model agreement: "
                f"{agreement['agreeing_models']}/"
                f"{self.minimum_agreeing_models}"
            )

        approved = not reasons

        return {
            "approved": approved,
            "decision": (
                "SIGNAL"
                if approved
                else "WAIT"
            ),
            "published_prediction": (
                candidate
                if approved
                else None
            ),
            "calibrated_confidence": (
                statistics[
                    "calibrated_confidence"
                ]
            ),
            "raw_confidence": raw_confidence,
            "rolling_accuracy": (
                statistics["rolling_accuracy"]
            ),
            "rolling_samples": (
                statistics["rolling_samples"]
            ),
            "lifetime_accuracy": (
                statistics[
                    "lifetime_accuracy"
                ]
            ),
            "lifetime_samples": (
                statistics[
                    "lifetime_samples"
                ]
            ),
            "agreement": agreement,

            "evidence_scope": (
                statistics["evidence_scope"]
            ),

            "rolling_lower_bound": (
                statistics[
                    "rolling_lower_bound"
                ]
            ),
            "rolling_upper_bound": (
                statistics[
                    "rolling_upper_bound"
                ]
            ),

            "last20_accuracy": (
                statistics["last20_accuracy"]
            ),
            "last20_samples": (
                statistics["last20_samples"]
            ),

            "last50_accuracy": (
                statistics["last50_accuracy"]
            ),
            "last50_samples": (
                statistics["last50_samples"]
            ),
            "last50_upper_bound": (
                statistics[
                    "last50_upper_bound"
                ]
            ),

            "last100_accuracy": (
                statistics["last100_accuracy"]
            ),
            "last100_samples": (
                statistics["last100_samples"]
            ),

            "current_streak_result": (
                statistics[
                    "current_streak_result"
                ]
            ),
            "current_streak_count": (
                statistics[
                    "current_streak_count"
                ]
            ),

            "statistically_above_baseline": (
                statistics[
                    "statistically_above_baseline"
                ]
            ),

            "recent_deterioration": (
                statistics[
                    "recent_deterioration"
                ]
            ),

            "market_qualified": (
                approved
                and statistics[
                    "statistically_above_baseline"
                ]
                and not statistics[
                    "recent_deterioration"
                ]
            ),

            "blocking_reasons": reasons,
        }
