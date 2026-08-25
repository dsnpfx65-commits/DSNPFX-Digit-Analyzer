from collections import Counter
from typing import Iterable


class DigitAnalyzer:
    """Analyses recent last-digit data from the tick buffer."""

    def __init__(self, digits: Iterable[int]):
        self.digits = [int(digit) for digit in digits]

        for digit in self.digits:
            if digit < 0 or digit > 9:
                raise ValueError("Every digit must be between 0 and 9")

    def total_ticks(self) -> int:
        return len(self.digits)

    def digit_counts(self) -> dict[int, int]:
        counted = Counter(self.digits)
        return {digit: counted.get(digit, 0) for digit in range(10)}

    def digit_percentages(self) -> dict[int, float]:
        total = self.total_ticks()

        if total == 0:
            return {digit: 0.0 for digit in range(10)}

        counts = self.digit_counts()

        return {
            digit: round((counts[digit] / total) * 100, 2)
            for digit in range(10)
        }

    def hot_digits(self) -> list[int]:
        counts = self.digit_counts()
        highest = max(counts.values(), default=0)

        return [
            digit
            for digit, count in counts.items()
            if count == highest
        ]

    def cold_digits(self) -> list[int]:
        counts = self.digit_counts()
        lowest = min(counts.values(), default=0)

        return [
            digit
            for digit, count in counts.items()
            if count == lowest
        ]

    def odd_even_bias(self) -> dict[str, float]:
        total = self.total_ticks()

        if total == 0:
            return {"odd": 0.0, "even": 0.0}

        odd = sum(1 for digit in self.digits if digit % 2 != 0)
        even = total - odd

        return {
            "odd": round((odd / total) * 100, 2),
            "even": round((even / total) * 100, 2),
        }

    def under_over_bias(self) -> dict[str, float]:
        total = self.total_ticks()

        if total == 0:
            return {"under_5": 0.0, "over_4": 0.0}

        under_5 = sum(1 for digit in self.digits if digit <= 4)
        over_4 = total - under_5

        return {
            "under_5": round((under_5 / total) * 100, 2),
            "over_4": round((over_4 / total) * 100, 2),
        }

    def current_streak(self) -> dict[str, int | None]:
        if not self.digits:
            return {"digit": None, "length": 0}

        current_digit = self.digits[-1]
        length = 1

        for digit in reversed(self.digits[:-1]):
            if digit != current_digit:
                break
            length += 1

        return {
            "digit": current_digit,
            "length": length,
        }

    def longest_streak(self) -> dict[str, int | None]:
        if not self.digits:
            return {"digit": None, "length": 0}

        longest_digit = self.digits[0]
        longest_length = 1

        current_digit = self.digits[0]
        current_length = 1

        for digit in self.digits[1:]:
            if digit == current_digit:
                current_length += 1
            else:
                current_digit = digit
                current_length = 1

            if current_length > longest_length:
                longest_digit = current_digit
                longest_length = current_length

        return {
            "digit": longest_digit,
            "length": longest_length,
        }

    def market_condition(self) -> str:
        if self.total_ticks() < 20:
            return "INSUFFICIENT DATA"

        percentages = self.digit_percentages()
        highest = max(percentages.values())
        lowest = min(percentages.values())
        spread = highest - lowest

        if spread <= 5:
            return "BALANCED"

        if spread <= 10:
            return "MODERATELY IMBALANCED"

        return "HIGHLY IMBALANCED"

    def analysis_report(self) -> dict:
        return {
            "ticks_analysed": self.total_ticks(),
            "counts": self.digit_counts(),
            "percentages": self.digit_percentages(),
            "hot_digits": self.hot_digits(),
            "cold_digits": self.cold_digits(),
            "odd_even": self.odd_even_bias(),
            "under_over": self.under_over_bias(),
            "current_streak": self.current_streak(),
            "longest_streak": self.longest_streak(),
            "market_condition": self.market_condition(),
        }
    def analysis_report(self) -> dict:
        return {
            "ticks_analysed": self.total_ticks(),
            "counts": self.digit_counts(),
            "percentages": self.digit_percentages(),
            "hot_digits": self.hot_digits(),
            "cold_digits": self.cold_digits(),
            "odd_even": self.odd_even_bias(),
            "under_over": self.under_over_bias(),
            "current_streak": self.current_streak(),
            "longest_streak": self.longest_streak(),
            "market_condition": self.market_condition(),
        }


    def prediction_score(self) -> dict[int, float]:
        """
        Creates a weighted probability score for each digit.
        Higher score = stronger prediction candidate.
        """

        if self.total_ticks() < 20:
            return {digit: 0.0 for digit in range(10)}

        percentages = self.digit_percentages()
        scores = {}

        for digit in range(10):
            score = 0

            # Frequency weight
            score += percentages[digit] * 0.5

            # Recent appearance bonus
            recent = self.digits[-20:]
            recent_count = recent.count(digit)
            score += recent_count * 1.5

            # Cold digit opportunity
            if digit in self.cold_digits():
                score += 5

            scores[digit] = round(score, 2)

        return scores
        scores[digit] = round(score, 2)

        return scores


    def predict_next_digit(self) -> dict:
        scores = self.prediction_score()

        prediction = max(
            scores,
            key=scores.get
        )

        total_score = sum(scores.values())

        if total_score == 0:
            confidence = 0
        else:
            confidence = round(
                (scores[prediction] / total_score) * 100,
                2
            )

        if confidence >= 70:
            strength = "HIGH"
        elif confidence >= 55:
            strength = "MEDIUM"
        else:
            strength = "LOW"

        return {
            "prediction": prediction,
            "confidence": confidence,
            "strength": strength,
            "all_scores": scores,
        }
