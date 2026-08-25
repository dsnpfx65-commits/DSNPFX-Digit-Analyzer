from collections import defaultdict, Counter


class MarkovEngine:
    """
    DSNPFX Markov Chain Engine

    Learns digit-to-digit transitions:
    Example:
    3 -> 7 happens often
    """

    def __init__(self, digits):
        self.digits = [int(d) for d in digits]
        self.transitions = defaultdict(Counter)

        self.build_matrix()


    def build_matrix(self):
        for current, next_digit in zip(
            self.digits,
            self.digits[1:]
        ):
            self.transitions[current][next_digit] += 1


    def transition_counts(self, digit):
        return dict(
            self.transitions[int(digit)]
        )


    def transition_probabilities(self, digit):
        counts = self.transitions[int(digit)]

        total = sum(counts.values())

        if total == 0:
            return {}

        return {
            next_digit: round(
                (count / total) * 100,
                2
            )
            for next_digit, count in counts.items()
        }


    def predict_next(self, current_digit):
        probabilities = self.transition_probabilities(
            current_digit
        )

        if not probabilities:
            return None

        prediction = max(
            probabilities,
            key=probabilities.get
        )

        return {
            "current_digit": current_digit,
            "prediction": prediction,
            "confidence": probabilities[prediction],
            "probabilities": probabilities,
        }
