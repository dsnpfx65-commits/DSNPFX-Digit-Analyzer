"""DSNPFX V9 X2X research detector.

An X2X pattern is any three-digit suffix where the first and third digits
match (for example 5-2-5). This engine only exposes measurable research
telemetry; it does not claim that X2X predicts the next digit.
"""

from __future__ import annotations


class X2XResearchEngine:
    def __init__(self, digits):
        self.digits = [int(digit) for digit in digits]

    def analyse(self) -> dict:
        if len(self.digits) < 3:
            return {
                "active": False,
                "pattern": None,
                "outer_digit": None,
                "middle_digit": None,
                "occurrences": 0,
                "next_digit_counts": {},
                "candidate": None,
                "candidate_support": 0,
                "candidate_confidence": 0.0,
                "scope": "RESEARCH_ONLY",
            }

        pattern = tuple(self.digits[-3:])
        active = pattern[0] == pattern[2]

        if not active:
            return {
                "active": False,
                "pattern": pattern,
                "outer_digit": None,
                "middle_digit": None,
                "occurrences": 0,
                "next_digit_counts": {},
                "candidate": None,
                "candidate_support": 0,
                "candidate_confidence": 0.0,
                "scope": "RESEARCH_ONLY",
            }

        outer = pattern[0]
        middle = pattern[1]
        counts: dict[int, int] = {}
        occurrences = 0

        for index in range(len(self.digits) - 3):
            prior = tuple(self.digits[index:index + 3])
            if prior != pattern:
                continue
            next_digit = int(self.digits[index + 3])
            counts[next_digit] = counts.get(next_digit, 0) + 1
            occurrences += 1

        candidate = None
        candidate_support = 0
        candidate_confidence = 0.0

        if counts:
            candidate, candidate_support = max(
                counts.items(),
                key=lambda item: (item[1], -item[0]),
            )
            candidate_confidence = round(
                candidate_support / occurrences * 100.0,
                2,
            ) if occurrences else 0.0

        return {
            "active": True,
            "pattern": pattern,
            "outer_digit": outer,
            "middle_digit": middle,
            "occurrences": occurrences,
            "next_digit_counts": counts,
            "candidate": candidate,
            "candidate_support": candidate_support,
            "candidate_confidence": candidate_confidence,
            "scope": "RESEARCH_ONLY",
        }
