"""Research-only implementation of the 1000-tick hot-digit continuation idea.

The source strategy is intentionally reproduced as a measurable hypothesis:
use the most frequent displayed digit in the latest 1000 ticks as the next
one-tick DIGITMATCH candidate. This module does not assume that historical
frequency predicts the next tick and never publishes a production signal.
"""

from __future__ import annotations

from collections import Counter
import math


class Hot1000ContinuationEngine:
    """Measure the exact 1000-tick hot-digit continuation hypothesis."""

    WINDOW = 1000
    BASELINE_PROBABILITY = 0.10
    DIAGNOSTIC_WINDOWS = (100, 200, 500, 1000)

    def __init__(self, digits):
        self.digits = [int(digit) for digit in digits]
        for digit in self.digits:
            if not 0 <= digit <= 9:
                raise ValueError("Every digit must be between 0 and 9")

    @staticmethod
    def _unique_hot_digit(sample: list[int]) -> tuple[int | None, int, list[int]]:
        if not sample:
            return None, 0, []

        counts = Counter(sample)
        highest = max(counts.get(digit, 0) for digit in range(10))
        tied = [digit for digit in range(10) if counts.get(digit, 0) == highest]
        candidate = tied[0] if len(tied) == 1 else None
        return candidate, highest, tied

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

    def analyse(self) -> dict:
        samples_available = len(self.digits)
        if samples_available < self.WINDOW:
            return {
                "status": "COLLECTING",
                "scope": "RESEARCH_ONLY",
                "strategy": "HOT_1000_CONTINUATION",
                "contract_type": "DIGITMATCH",
                "duration": 1,
                "duration_unit": "t",
                "window": self.WINDOW,
                "samples": samples_available,
                "samples_required": self.WINDOW,
                "candidate": None,
                "frequency_pct": None,
                "deviation_vs_10pct_pp": None,
                "z_score": None,
                "unique_hot_digit": False,
                "forward_validation_required": True,
                "research_action": "COLLECT",
            }

        sample = self.digits[-self.WINDOW:]
        counts = Counter(sample)
        digit_counts = {digit: counts.get(digit, 0) for digit in range(10)}
        candidate, candidate_count, tied_hot_digits = self._unique_hot_digit(sample)

        if candidate is None:
            frequency_pct = candidate_count / self.WINDOW * 100.0
            deviation_pp = frequency_pct - 10.0
            z_score = self._z_score(candidate_count, self.WINDOW)
        else:
            frequency_pct = digit_counts[candidate] / self.WINDOW * 100.0
            deviation_pp = frequency_pct - 10.0
            z_score = self._z_score(digit_counts[candidate], self.WINDOW)

        window_hot_digits: dict[int, int | None] = {}
        agreeing_windows = 0
        completed_windows = 0
        for window in self.DIAGNOSTIC_WINDOWS:
            diagnostic_sample = self.digits[-window:]
            if len(diagnostic_sample) < window:
                continue
            hot_digit, _, _ = self._unique_hot_digit(diagnostic_sample)
            window_hot_digits[window] = hot_digit
            completed_windows += 1
            if candidate is not None and hot_digit == candidate:
                agreeing_windows += 1

        continuation_consistency_pct = (
            agreeing_windows / completed_windows * 100.0
            if completed_windows
            else 0.0
        )

        return {
            "status": "READY" if candidate is not None else "TIED_HOT_DIGITS",
            "scope": "RESEARCH_ONLY",
            "strategy": "HOT_1000_CONTINUATION",
            "contract_type": "DIGITMATCH",
            "duration": 1,
            "duration_unit": "t",
            "window": self.WINDOW,
            "samples": self.WINDOW,
            "samples_required": self.WINDOW,
            "candidate": candidate,
            "digit_counts": digit_counts,
            "tied_hot_digits": tied_hot_digits,
            "unique_hot_digit": candidate is not None,
            "frequency_pct": round(frequency_pct, 4),
            "baseline_probability_pct": 10.0,
            "deviation_vs_10pct_pp": round(deviation_pp, 4),
            "z_score": round(z_score, 4),
            "window_hot_digits": window_hot_digits,
            "agreeing_windows": agreeing_windows,
            "completed_diagnostic_windows": completed_windows,
            "continuation_consistency_pct": round(continuation_consistency_pct, 2),
            "forward_validation_required": True,
            "research_action": "FORWARD_TEST" if candidate is not None else "WAIT_TIE",
            "warning": (
                "A hot historical digit is not a calibrated next-tick probability. "
                "Promote only if prospective outcomes beat the relevant break-even rate."
            ),
        }
