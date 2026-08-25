from collections import Counter, defaultdict


class SequenceEngine:
    """
    DSNPFX support-aware N-gram sequence engine.

    Learns 2-, 3-, 4- and 5-digit contexts and the digit that followed each
    context. Longer patterns are only preferred when they have enough observed
    support; otherwise the engine backs off to a shorter context.
    """

    def __init__(self, digits):
        self.digits = [int(d) for d in digits]

        self.pattern_2 = defaultdict(Counter)
        self.pattern_3 = defaultdict(Counter)
        self.pattern_4 = defaultdict(Counter)
        self.pattern_5 = defaultdict(Counter)

        self.build_patterns()

    def build_patterns(self):
        for i in range(len(self.digits) - 2):
            pattern = (self.digits[i], self.digits[i + 1])
            self.pattern_2[pattern][self.digits[i + 2]] += 1

        for i in range(len(self.digits) - 3):
            pattern = (
                self.digits[i],
                self.digits[i + 1],
                self.digits[i + 2],
            )
            self.pattern_3[pattern][self.digits[i + 3]] += 1

        for i in range(len(self.digits) - 4):
            pattern = (
                self.digits[i],
                self.digits[i + 1],
                self.digits[i + 2],
                self.digits[i + 3],
            )
            self.pattern_4[pattern][self.digits[i + 4]] += 1

        for i in range(len(self.digits) - 5):
            pattern = (
                self.digits[i],
                self.digits[i + 1],
                self.digits[i + 2],
                self.digits[i + 3],
                self.digits[i + 4],
            )
            self.pattern_5[pattern][self.digits[i + 5]] += 1

    def _build_result(self, pattern, results, pattern_length):
        if not results:
            return None

        total = sum(results.values())
        prediction = max(
            results,
            key=lambda digit: (results[digit], -digit),
        )
        support = int(total)
        confidence = round(results[prediction] / total * 100.0, 2)

        return {
            "pattern": pattern,
            "pattern_length": pattern_length,
            "prediction": prediction,
            "confidence": confidence,
            "support": support,
            "matches": dict(results),
        }

    def _predict_length(self, length):
        if len(self.digits) < length + 1:
            return None

        pattern = tuple(self.digits[-length:])
        table = getattr(self, f"pattern_{length}")
        return self._build_result(pattern, table[pattern], length)

    def predict_from_two(self):
        return self._predict_length(2)

    def predict_from_three(self):
        return self._predict_length(3)

    def predict_from_four(self):
        return self._predict_length(4)

    def predict_from_five(self):
        return self._predict_length(5)

    def predict(self, min_support: int = 3):
        """Return the longest context with enough historical support.

        A high percentage from one or two historical occurrences is not treated
        as reliable evidence. If no context reaches ``min_support``, the best
        available result is returned as research metadata with ``qualified``
        set to False so callers can keep it out of production voting.
        """
        min_support = max(1, int(min_support))
        candidates = []

        for length in (5, 4, 3, 2):
            result = self._predict_length(length)
            if result is None:
                continue

            result = dict(result)
            result["qualified"] = result["support"] >= min_support
            result["minimum_support"] = min_support
            candidates.append(result)

            if result["qualified"]:
                return result

        if not candidates:
            return None

        # Research-only fallback: choose the context with the most support,
        # breaking ties in favour of the longer pattern.
        return max(
            candidates,
            key=lambda item: (item["support"], item["pattern_length"]),
        )
