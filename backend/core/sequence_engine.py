from collections import Counter, defaultdict


class SequenceEngine:
    """
    DSNPFX Sequence Memory Engine

    Learns:
    - 2 digit patterns
    - 3 digit patterns
    - 4 digit patterns
    - 5 digit patterns
    - What digit usually follows
    """

    def __init__(self, digits):
        self.digits = [int(d) for d in digits]

        self.pattern_2 = defaultdict(Counter)
        self.pattern_3 = defaultdict(Counter)
        self.pattern_4 = defaultdict(Counter)
        self.pattern_5 = defaultdict(Counter)

        self.build_patterns()

    def build_patterns(self):
        # Two digit sequence memory
        for i in range(len(self.digits) - 2):
            pattern = (
                self.digits[i],
                self.digits[i + 1],
            )

            next_digit = self.digits[i + 2]
            self.pattern_2[pattern][next_digit] += 1

        # Three digit sequence memory
        for i in range(len(self.digits) - 3):
            pattern = (
                self.digits[i],
                self.digits[i + 1],
                self.digits[i + 2],
            )

            next_digit = self.digits[i + 3]
            self.pattern_3[pattern][next_digit] += 1

        # Four digit sequence memory
        for i in range(len(self.digits) - 4):
            pattern = (
                self.digits[i],
                self.digits[i + 1],
                self.digits[i + 2],
                self.digits[i + 3],
            )

            next_digit = self.digits[i + 4]
            self.pattern_4[pattern][next_digit] += 1

        # Five digit sequence memory
        for i in range(len(self.digits) - 5):
            pattern = (
                self.digits[i],
                self.digits[i + 1],
                self.digits[i + 2],
                self.digits[i + 3],
                self.digits[i + 4],
            )

            next_digit = self.digits[i + 5]
            self.pattern_5[pattern][next_digit] += 1

    def _build_result(self, pattern, results):
        if not results:
            return None

        total = sum(results.values())

        prediction = max(
            results,
            key=results.get,
        )

        confidence = round(
            (results[prediction] / total) * 100,
            2,
        )

        return {
            "pattern": pattern,
            "prediction": prediction,
            "confidence": confidence,
            "support": total,
            "matches": dict(results),
        }

    def predict_from_two(self):
        if len(self.digits) < 3:
            return None

        pattern = tuple(self.digits[-2:])
        results = self.pattern_2[pattern]

        return self._build_result(pattern, results)

    def predict_from_three(self):
        if len(self.digits) < 4:
            return None

        pattern = tuple(self.digits[-3:])
        results = self.pattern_3[pattern]

        return self._build_result(pattern, results)

    def predict_from_four(self):
        if len(self.digits) < 5:
            return None

        pattern = tuple(self.digits[-4:])
        results = self.pattern_4[pattern]

        return self._build_result(pattern, results)

    def predict_from_five(self):
        if len(self.digits) < 6:
            return None

        pattern = tuple(self.digits[-5:])
        results = self.pattern_5[pattern]

        return self._build_result(pattern, results)

    def predict(self):
        """
        Uses the longest matching pattern first.

        Backoff order:
        5 digits -> 4 digits -> 3 digits -> 2 digits
        """

        predictors = (
            self.predict_from_five,
            self.predict_from_four,
            self.predict_from_three,
            self.predict_from_two,
        )

        for predictor in predictors:
            result = predictor()

            if result is not None:
                return result

        return None
