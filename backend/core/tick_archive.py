"""
DSNPFX V8.3 Phase 3A.2
Read-only-for-production multi-market historical tick archive.

This component records accepted live ticks for offline V9
research. It does not participate in prediction decisions,
model memory, weighting, Edge Score, or signal publication.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
import sqlite3


DEFAULT_DATABASE = Path(
    "data/dsnpfx_ticks.db"
)


class MultiMarketTickArchive:
    def __init__(
        self,
        database=DEFAULT_DATABASE,
    ):
        self.database = Path(database)

        self.database.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.lock = RLock()

        self.connection = sqlite3.connect(
            self.database,
            timeout=30,
            check_same_thread=False,
        )

        self.connection.row_factory = sqlite3.Row

        with self.lock:
            self.connection.execute(
                "PRAGMA journal_mode=WAL"
            )

            self.connection.execute(
                "PRAGMA synchronous=NORMAL"
            )

            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ticks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    quote REAL NOT NULL,
                    displayed_quote TEXT NOT NULL,
                    digit INTEGER NOT NULL
                        CHECK (digit BETWEEN 0 AND 9),
                    epoch INTEGER NOT NULL,
                    pip_size INTEGER,
                    created_at DATETIME
                        DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, epoch)
                )
                """
            )

            self.connection.execute(
                """
                CREATE INDEX IF NOT EXISTS
                    idx_ticks_symbol_epoch
                ON ticks(symbol, epoch)
                """
            )

            self.connection.commit()

    def add_tick(
        self,
        *,
        symbol,
        quote,
        displayed_quote,
        digit,
        epoch,
        pip_size,
    ) -> bool:
        symbol = str(symbol)
        digit = int(digit)
        epoch = int(epoch)

        if not 0 <= digit <= 9:
            raise ValueError(
                "digit must be between 0 and 9"
            )

        with self.lock:
            cursor = self.connection.execute(
                """
                INSERT OR IGNORE INTO ticks (
                    symbol,
                    quote,
                    displayed_quote,
                    digit,
                    epoch,
                    pip_size
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    float(quote),
                    str(displayed_quote),
                    digit,
                    epoch,
                    (
                        int(pip_size)
                        if pip_size is not None
                        else None
                    ),
                ),
            )

            self.connection.commit()

            return cursor.rowcount > 0

    def count(
        self,
        symbol=None,
    ) -> int:
        with self.lock:
            if symbol is None:
                row = self.connection.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM ticks
                    """
                ).fetchone()
            else:
                row = self.connection.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM ticks
                    WHERE symbol = ?
                    """,
                    (str(symbol),),
                ).fetchone()

        return int(row["n"] or 0)

    def close(self):
        with self.lock:
            self.connection.close()
