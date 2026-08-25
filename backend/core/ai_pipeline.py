from backend.core.digit_analyzer import DigitAnalyzer
from backend.core.markov_engine import MarkovEngine
from backend.core.sequence_engine import SequenceEngine
from backend.core.transition_model import TransitionModel
from backend.core.decision_engine import DecisionEngine


class DSPFXAIPipeline:
    """
    DSNPFX multi-model digit prediction pipeline.

    Active models:
    - Frequency
    - Markov
    - Sequence
    - Transition

    Momentum remains disabled until an independent momentum
    algorithm is implemented.
    """

    def __init__(
        self,
        digits,
        weights=None,
        prediction_overrides=None,
    ):
        self.digits = [int(digit) for digit in digits]
        self.weights = weights
        self.prediction_overrides = (
            prediction_overrides or {}
        )

        self.analyzer = DigitAnalyzer(self.digits)
        self.markov = MarkovEngine(self.digits)
        self.sequence = SequenceEngine(self.digits)

        self.transition = TransitionModel()

        for previous_digit, current_digit in zip(
            self.digits,
            self.digits[1:],
        ):
            self.transition.learn(
                previous_digit,
                current_digit,
            )

    def run(self):
        if not self.digits:
            return {
                "prediction": None,
                "confidence": 0,
                "strength": "LOW",
                "decision": "WAIT",
                "market_condition": "INSUFFICIENT_DATA",
                "model_predictions": {},
                "model_weights": {},
            }

        # Frequency model
        frequency_result = (
            self.analyzer.predict_next_digit()
        )

        frequency_prediction = (
            frequency_result.get("prediction")
            if frequency_result
            else None
        )

        # Markov model
        markov_result = self.markov.predict_next(
            self.digits[-1]
        )

        markov_prediction = (
            markov_result.get("prediction")
            if markov_result
            else None
        )

        # Sequence model:
        # prefer the more specific 3-digit pattern and
        # fall back to the 2-digit pattern when unavailable.
        sequence_result = self.sequence.predict_from_three()
        sequence_pattern_length = 3

        if sequence_result is None:
            sequence_result = self.sequence.predict_from_two()
            sequence_pattern_length = 2

        sequence_prediction = (
            sequence_result.get("prediction")
            if sequence_result
            else None
        )

        # Independent TransitionModel implementation.
        # Its performance will be measured separately from Markov.
        current_digit = self.digits[-1]

        transition_prediction = (
            self.transition.predict(current_digit)
        )

        transition_confidence = (
            self.transition.confidence(current_digit)
        )

        transition_samples = (
            self.transition.samples(current_digit)
        )

        # Apply promoted specialist overrides when supplied.
        frequency_prediction = (
            self.prediction_overrides.get(
                "frequency",
                frequency_prediction,
            )
        )

        markov_prediction = (
            self.prediction_overrides.get(
                "markov",
                markov_prediction,
            )
        )

        sequence_prediction = (
            self.prediction_overrides.get(
                "sequence",
                sequence_prediction,
            )
        )

        transition_prediction = (
            self.prediction_overrides.get(
                "transition",
                transition_prediction,
            )
        )

        # Momentum stays disabled.
        momentum_prediction = None

        decision = DecisionEngine(
            frequency=frequency_prediction,
            markov=markov_prediction,
            sequence=sequence_prediction,
            momentum=momentum_prediction,
            transition=transition_prediction,
            weights=self.weights,
        )

        result = decision.analyze()

        result["model_predictions"] = {
            "frequency": frequency_prediction,
            "markov": markov_prediction,
            "sequence": sequence_prediction,
            "transition": transition_prediction,
            "momentum": momentum_prediction,
        }

        # Store the weights actually used by DecisionEngine.
        result["model_weights"] = (
            decision.weights.copy()
        )

        result["model_metadata"] = {
            "sequence": {
                "pattern_length": sequence_pattern_length,
                "pattern": (
                    sequence_result.get("pattern")
                    if sequence_result
                    else None
                ),
                "confidence": (
                    sequence_result.get("confidence", 0.0)
                    if sequence_result
                    else 0.0
                ),
                "matches": (
                    sequence_result.get("matches", {})
                    if sequence_result
                    else {}
                ),
            },
            "transition": {
                "confidence": transition_confidence,
                "samples": transition_samples,
                "probabilities": (
                    self.transition.probabilities(
                        current_digit
                    )
                ),
            }
        }

        return result
