"""Research-only cold-digit mean-reversion hypotheses.

This engine measures the idea that the least-frequent digit in a recent window
might reappear on the next tick. It deliberately treats that idea as a
hypothesis, not as a statement that a rare digit is "due".
"""

from __future__ import annotations

from collections import Counter
import math


class ColdReversionEngine:
    """Analyse unique least-frequent digits over 200/500/1000 ticks."""

    WINDOWS = (200, 500, 1000)
    BASELINE_PROBABILITY = 0.10

    def __init__(self, digits):
        self.digits = [int(digit) for digit in digits]
        for digit in self.digits:
            if not 0 <= digit <= 9:
                raise ValueError("Every digit must be between 0 and 9")

    @staticmethod
    def _unique_cold_digit(sample: list[int]) -> tuple[int | None, int, list[int]]:
        if not sample:
            return None, 0, []

        counts = Counter(sample)
        minimum = min(counts.get(digit, 0) for digit in range(10))
        tied = [digit for digit in range(10) if counts.get(digit, 0) == minimum]
        candidate = tied[0] if len(tied) == 1 else None
        return candidate, minimum, tied

    @classmethod
    def _z_score(cls, count: int, samples: int) -> float:
        if samples <= 0:
            return 0.0
        observed = count / samples
        standard_error = math.sqrt(
            cls.BASELINE_PROBABILITY
            * (1.0 - cls.BASELINE_PROBABILITY)
            / samples
        )
        if standard_error <= 0.0:
            return 0.0
        return (observed - cls.BASELINE_PROBABILITY) / standard_error

    def _window_report(self, window: int) -> dict:
        if len(self.digits) < window:
            return {
                "status": "COLLECTING",
                "window": window,
                "samples": len(self.digits),
                "samples_required": window,
                "candidate": None,
                "frequency_pct": None,
                "deviation_vs_10pct_pp": None,
                "z_score": None,
                "unique_cold_digit": False,
                "research_action": "COLLECT",
            }

        sample = self.digits[-window:]
        counts = Counter(sample)
        digit_counts = {digit: counts.get(digit, 0) for digit in range(10)}
        candidate, candidate_count, tied = self._unique_cold_digit(sample)
        frequency_pct = candidate_count / window * 100.0

        return {
            "status": "READY" if candidate is not None else "TIED_COLD_DIGITS",
            "window": window,
            "samples": window,
            "samples_required": window,
            "candidate": candidate,
            "digit_counts": digit_counts,
            "tied_cold_digits": tied,
            "unique_cold_digit": candidate is not None,
            "frequency_pct": round(frequency_pct, 4),
            "baseline_probability_pct": 10.0,
            "deviation_vs_10pct_pp": round(frequency_pct - 10.0, 4),
            "z_score": round(self._z_score(candidate_count, window), 4),
            "research_action": "FORWARD_TEST" if candidate is not None else "WAIT_TIE",
        }

    def analyse(self) -> dict:
        reports = {window: self._window_report(window) for window in self.WINDOWS}
        ready = [report for report in reports.values() if report["candidate"] is not None]

        longest_ready = max(ready, key=lambda report: report["window"]) if ready else None

        return {
            "status": "READY" if ready else "COLLECTING",
            "scope": "RESEARCH_ONLY",
            "strategy": "COLD_REVERSION",
            "contract_type": "DIGITMATCH",
            "duration": 1,
            "duration_unit": "t",
            "windows": reports,
            "primary_window": longest_ready["window"] if longest_ready else None,
            "primary_candidate": longest_ready["candidate"] if longest_ready else None,
            "forward_validation_required": True,
            "warning": (
                "A rare digit is not automatically due. This hypothesis must be "
                "validated prospectively against the 10% baseline and live break-even rate."
            ),
        }
