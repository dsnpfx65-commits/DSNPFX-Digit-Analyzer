"""Research-only 20-tick cold-digit DIGITDIFF hypothesis.

The strategy mirrors the observable rule from the supplied Deriv Analyzer
video: find the least-frequent displayed digit in the latest 20 ticks, then
hypothesise that the next tick will differ from that digit.

This module never treats a rare digit as "due", never emits a production
signal, and never equates the natural ~90% DIGITDIFF hit rate with trading
edge. Profitability must be measured prospectively against the live proposal
break-even probability.
"""

from __future__ import annotations

from collections import Counter
import math


class Cold20DiffersEngine:
    WINDOW = 20
    MATCH_BASELINE_PCT = 10.0
    DIFFER_BASELINE_PCT = 90.0

    def __init__(self, digits):
        self.digits = [int(digit) for digit in digits]
        for digit in self.digits:
            if not 0 <= digit <= 9:
                raise ValueError("Every digit must be between 0 and 9")

    @staticmethod
    def _unique_cold_digit(sample: list[int]) -> tuple[int | None, int, list[int]]:
        counts = Counter(sample)
        minimum = min(counts.get(digit, 0) for digit in range(10))
        tied = [digit for digit in range(10) if counts.get(digit, 0) == minimum]
        candidate = tied[0] if len(tied) == 1 else None
        return candidate, minimum, tied

    @staticmethod
    def _z_score(count: int, samples: int) -> float:
        if samples <= 0:
            return 0.0
        observed = count / samples
        baseline = 0.10
        standard_error = math.sqrt(baseline * (1.0 - baseline) / samples)
        if standard_error <= 0.0:
            return 0.0
        return (observed - baseline) / standard_error

    def analyse(self) -> dict:
        samples = len(self.digits)
        if samples < self.WINDOW:
            return {
                "status": "COLLECTING",
                "scope": "RESEARCH_ONLY",
                "strategy": "COLD_20_DIFFERS",
                "contract_type": "DIGITDIFF",
                "duration": 1,
                "duration_unit": "t",
                "window": self.WINDOW,
                "samples": samples,
                "samples_required": self.WINDOW,
                "candidate": None,
                "cold_frequency_pct": None,
                "historical_differ_rate_pct": None,
                "differ_baseline_pct": self.DIFFER_BASELINE_PCT,
                "descriptive_deviation_vs_90pct_pp": None,
                "z_score_vs_10pct_match_baseline": None,
                "research_action": "COLLECT",
                "forward_validation_required": True,
            }

        sample = self.digits[-self.WINDOW:]
        counts = Counter(sample)
        digit_counts = {digit: counts.get(digit, 0) for digit in range(10)}
        candidate, candidate_count, tied = self._unique_cold_digit(sample)
        cold_frequency_pct = candidate_count / self.WINDOW * 100.0
        historical_differ_rate_pct = 100.0 - cold_frequency_pct

        return {
            "status": "READY" if candidate is not None else "TIED_COLD_DIGITS",
            "scope": "RESEARCH_ONLY",
            "strategy": "COLD_20_DIFFERS",
            "contract_type": "DIGITDIFF",
            "duration": 1,
            "duration_unit": "t",
            "window": self.WINDOW,
            "samples": self.WINDOW,
            "samples_required": self.WINDOW,
            "candidate": candidate,
            "digit_counts": digit_counts,
            "tied_cold_digits": tied,
            "unique_cold_digit": candidate is not None,
            "cold_frequency_pct": round(cold_frequency_pct, 4),
            "historical_differ_rate_pct": round(historical_differ_rate_pct, 4),
            "differ_baseline_pct": self.DIFFER_BASELINE_PCT,
            "descriptive_deviation_vs_90pct_pp": round(
                historical_differ_rate_pct - self.DIFFER_BASELINE_PCT,
                4,
            ),
            "z_score_vs_10pct_match_baseline": round(
                self._z_score(candidate_count, self.WINDOW),
                4,
            ),
            "research_action": "FORWARD_TEST" if candidate is not None else "WAIT_TIE",
            "forward_validation_required": True,
            "warning": (
                "The historical 20-tick differ rate is descriptive only, not a "
                "next-tick probability. Forward accuracy must beat the live "
                "DIGITDIFF break-even probability before this has trading edge."
            ),
        }
