"""
DSNPFX Market Quality Gate

Classifies symbols from resolved next-digit outcomes so
constrained markets cannot enter the normal ten-digit
premium leaderboard.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3


DEFAULT_DATABASE = Path(
    "backend/data/multi_market_learning.db"
)


@dataclass(frozen=True)
class MarketQuality:
    symbol: str
    classification: str
    eligible_for_global_learning: bool
    resolved_samples: int
    distinct_digits: int
    top_digit: int | None
    top_digit_share: float
    accuracy: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class MarketQualityGate:
    """
    Market classifications:

    TEN_DIGIT
        Sufficient samples and all ten digits observed.
        Eligible for premium ranking.

    LOW_SAMPLE
        Fewer than the required resolved samples.
        Eligible for shadow learning only.

    CONSTRAINED
        Fewer than ten distinct actual digits after the
        minimum sample threshold.
        Research only.

    HIGHLY_SKEWED
        Ten digits exist, but one digit dominates beyond
        the accepted concentration threshold.
        Research only.
    """

    def __init__(
        self,
        database=DEFAULT_DATABASE,
        min_samples=100,
        min_distinct_digits=10,
        max_top_digit_share=30.0,
    ):
        self.database = Path(database)
        self.min_samples = int(min_samples)
        self.min_distinct_digits = int(
            min_distinct_digits
        )
        self.max_top_digit_share = float(
            max_top_digit_share
        )

        if self.min_samples < 1:
            raise ValueError(
                "min_samples must be at least 1"
            )

        if not 1 <= self.min_distinct_digits <= 10:
            raise ValueError(
                "min_distinct_digits must be between 1 and 10"
            )

        if not 0 < self.max_top_digit_share <= 100:
            raise ValueError(
                "max_top_digit_share must be between 0 and 100"
            )

    def _connect(self):
        if not self.database.exists():
            raise FileNotFoundError(
                f"Learning database not found: "
                f"{self.database}"
            )

        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _classify(
        self,
        symbol: str,
        rows,
    ) -> MarketQuality:
        rows = list(rows)
        resolved_samples = len(rows)

        digit_counts = Counter(
            int(row["actual"])
            for row in rows
        )

        wins = sum(
            1
            for row in rows
            if row["result"] == "WIN"
        )

        accuracy = (
            round(
                wins / resolved_samples * 100,
                2,
            )
            if resolved_samples
            else 0.0
        )

        distinct_digits = len(digit_counts)

        if digit_counts:
            top_digit, top_count = (
                digit_counts.most_common(1)[0]
            )
        else:
            top_digit = None
            top_count = 0

        top_digit_share = (
            round(
                top_count / resolved_samples * 100,
                2,
            )
            if resolved_samples
            else 0.0
        )

        if resolved_samples < self.min_samples:
            classification = "LOW_SAMPLE"
            eligible = False
            reason = (
                f"Only {resolved_samples} resolved samples; "
                f"{self.min_samples} required"
            )

        elif distinct_digits < self.min_distinct_digits:
            classification = "CONSTRAINED"
            eligible = False
            reason = (
                f"Only {distinct_digits} distinct actual digits; "
                f"{self.min_distinct_digits} required"
            )

        elif top_digit_share > self.max_top_digit_share:
            classification = "HIGHLY_SKEWED"
            eligible = False
            reason = (
                f"Top digit share {top_digit_share}% exceeds "
                f"{self.max_top_digit_share}%"
            )

        else:
            classification = "TEN_DIGIT"
            eligible = True
            reason = (
                "Sufficient samples and ten-digit diversity"
            )

        return MarketQuality(
            symbol=str(symbol),
            classification=classification,
            eligible_for_global_learning=eligible,
            resolved_samples=resolved_samples,
            distinct_digits=distinct_digits,
            top_digit=top_digit,
            top_digit_share=top_digit_share,
            accuracy=accuracy,
            reason=reason,
        )

    def assess(self, symbol: str) -> MarketQuality:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT actual, result
                FROM predictions
                WHERE symbol = ?
                  AND actual IS NOT NULL
                  AND result IN ('WIN', 'LOSS')
                ORDER BY id
                """,
                (symbol,),
            ).fetchall()

        return self._classify(
            str(symbol),
            rows,
        )

    def assess_all_map(
        self,
    ) -> dict[str, MarketQuality]:
        """
        Load all resolved outcomes in one database query.

        This avoids opening a new SQLite connection for every
        market during each scanner cycle.
        """

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT symbol, actual, result
                FROM predictions
                WHERE symbol IS NOT NULL
                  AND actual IS NOT NULL
                  AND result IN ('WIN', 'LOSS')
                ORDER BY symbol, id
                """
            ).fetchall()

        grouped = defaultdict(list)

        for row in rows:
            grouped[str(row["symbol"])].append(row)

        return {
            symbol: self._classify(
                symbol,
                symbol_rows,
            )
            for symbol, symbol_rows
            in grouped.items()
        }

    def assess_all(self) -> list[MarketQuality]:
        return list(
            self.assess_all_map().values()
        )

    def eligible_symbols(self) -> list[str]:
        return sorted(
            quality.symbol
            for quality in self.assess_all()
            if quality.classification == "TEN_DIGIT"
        )
