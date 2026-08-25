from collections import Counter, defaultdict


class TransitionModel:
    """
    First-order transition probability model.
    Learns:
        previous_digit -> next_digit
    """

    def __init__(self):
        self.transitions = defaultdict(Counter)

    def learn(self, previous_digit, current_digit):
        previous_digit = int(previous_digit)
        current_digit = int(current_digit)

        self.transitions[previous_digit][current_digit] += 1

    def predict(self, current_digit):
        current_digit = int(current_digit)

        if current_digit not in self.transitions:
            return None

        counts = self.transitions[current_digit]

        if not counts:
            return None

        return counts.most_common(1)[0][0]

    def confidence(self, current_digit):
        current_digit = int(current_digit)

        if current_digit not in self.transitions:
            return 0.0

        counts = self.transitions[current_digit]

        total = sum(counts.values())

        if total == 0:
            return 0.0

        best = counts.most_common(1)[0][1]

        return round(best / total * 100, 2)

    def probabilities(self, current_digit):
        current_digit = int(current_digit)

        if current_digit not in self.transitions:
            return {}

        counts = self.transitions[current_digit]

        total = sum(counts.values())

        if total == 0:
            return {}

        return {
            digit: round(count / total, 4)
            for digit, count in counts.items()
        }

    def samples(self, current_digit):
        current_digit = int(current_digit)

        if current_digit not in self.transitions:
            return 0

        return sum(self.transitions[current_digit].values())

    def reset(self):
        self.transitions.clear()
