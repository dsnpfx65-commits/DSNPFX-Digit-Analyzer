from collections import Counter


class MarketRegime:

    def __init__(self, digits):

        self.digits = digits[-50:]


    def analyse(self):

        if len(self.digits) < 20:

            return {
                "regime": "UNKNOWN",
                "confidence": 0
            }

        unique_digits = len(set(self.digits))

        repeats = sum(
            1
            for i in range(1, len(self.digits))
            if self.digits[i] == self.digits[i - 1]
        )

        frequencies = Counter(self.digits)

        dominant = max(frequencies.values())

        if repeats >= 8:

            regime = "REPEATING"

        elif dominant >= 10:

            regime = "TRENDING"

        elif unique_digits >= 9:

            regime = "RANDOM"

        else:

            regime = "MIXED"

        confidence = round(
            dominant / len(self.digits) * 100,
            2
        )

        return {
            "regime": regime,
            "confidence": confidence,
            "unique_digits": unique_digits,
            "repeats": repeats,
            "dominant_count": dominant
        }
