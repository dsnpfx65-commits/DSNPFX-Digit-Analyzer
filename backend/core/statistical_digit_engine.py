"""DSNPFX V9 research-only statistical digit diagnostics.

This module does not publish production signals. It measures how far the
observed last-digit distribution departs from the 10% exact-digit baseline and
produces research candidates that must earn forward evidence before promotion.
"""

from __future__ import annotations

from collections import Counter
import math


class StatisticalDigitEngine:
    RANDOM_PROBABILITY = 0.10
    WINDOWS = (20, 50, 100, 250, 500, 1000)

    def __init__(self, digits):
        self.digits = [int(digit) for digit in digits]
        for digit in self.digits:
            if not 0 <= digit <= 9:
                raise ValueError("Every digit must be between 0 and 9")

    @staticmethod
    def _entropy(counts: dict[int, int], samples: int) -> tuple[float, float]:
        if samples <= 0:
            return 0.0, 0.0

        entropy = 0.0
        for count in counts.values():
            if count <= 0:
                continue
            probability = count / samples
            entropy -= probability * math.log2(probability)

        maximum = math.log2(10)
        normalised = entropy / maximum * 100.0 if maximum else 0.0
        return round(entropy, 6), round(normalised, 2)

    @classmethod
    def _window_report(cls, digits: list[int], window: int) -> dict:
        sample = digits[-window:]
        samples = len(sample)
        counts_raw = Counter(sample)
        counts = {digit: counts_raw.get(digit, 0) for digit in range(10)}

        if samples <= 0:
            return {
                "window": window,
                "samples": 0,
                "counts": counts,
                "percentages": {digit: 0.0 for digit in range(10)},
                "z_scores": {digit: 0.0 for digit in range(10)},
                "chi_square": 0.0,
                "entropy_bits": 0.0,
                "entropy_normalised": 0.0,
                "hot_digit": None,
                "cold_digit": None,
                "max_abs_z": 0.0,
            }

        expected_count = samples * cls.RANDOM_PROBABILITY
        standard_error = math.sqrt(
            cls.RANDOM_PROBABILITY
            * (1.0 - cls.RANDOM_PROBABILITY)
            / samples
        )

        percentages = {}
        z_scores = {}
        chi_square = 0.0

        for digit in range(10):
            proportion = counts[digit] / samples
            percentages[digit] = round(proportion * 100.0, 2)
            z_scores[digit] = round(
                (proportion - cls.RANDOM_PROBABILITY) / standard_error,
                4,
            ) if standard_error > 0 else 0.0

            if expected_count > 0:
                difference = counts[digit] - expected_count
                chi_square += difference * difference / expected_count

        entropy_bits, entropy_normalised = cls._entropy(counts, samples)
        hot_digit = max(range(10), key=lambda digit: (z_scores[digit], -digit))
        cold_digit = min(range(10), key=lambda digit: (z_scores[digit], digit))
        max_abs_z = max(abs(value) for value in z_scores.values())

        return {
            "window": window,
            "samples": samples,
            "counts": counts,
            "percentages": percentages,
            "z_scores": z_scores,
            "chi_square": round(chi_square, 4),
            "entropy_bits": entropy_bits,
            "entropy_normalised": entropy_normalised,
            "hot_digit": hot_digit,
            "cold_digit": cold_digit,
            "max_abs_z": round(max_abs_z, 4),
        }

    def analyse(self) -> dict:
        reports = {
            window: self._window_report(self.digits, window)
            for window in self.WINDOWS
            if len(self.digits) >= min(window, 20)
        }

        if not reports:
            return {
                "status": "INSUFFICIENT_DATA",
                "windows": {},
                "primary_window": None,
                "hot_continuation": None,
                "cold_reversion": None,
            }

        # Prefer 100 ticks when available; otherwise use the largest completed
        # research window. The candidates are telemetry, not trade signals.
        if len(self.digits) >= 100 and 100 in reports:
            primary_window = 100
        else:
            primary_window = max(reports)

        primary = reports[primary_window]

        return {
            "status": "READY",
            "windows": reports,
            "primary_window": primary_window,
            "hot_continuation": primary["hot_digit"],
            "cold_reversion": primary["cold_digit"],
            "chi_square": primary["chi_square"],
            "entropy_normalised": primary["entropy_normalised"],
            "max_abs_z": primary["max_abs_z"],
            "baseline_probability": self.RANDOM_PROBABILITY,
            "scope": "RESEARCH_ONLY",
        }
