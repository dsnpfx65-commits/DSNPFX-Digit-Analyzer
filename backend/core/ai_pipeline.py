from backend.core.digit_analyzer import DigitAnalyzer
from backend.core.markov_engine import MarkovEngine
from backend.core.sequence_engine import SequenceEngine
from backend.core.transition_model import TransitionModel
from backend.core.decision_engine import DecisionEngine
from backend.core.statistical_digit_engine import StatisticalDigitEngine
from backend.core.x2x_research_engine import X2XResearchEngine
from backend.core.probability_analysis import ProbabilityAnalysisEngine
from backend.core.hot_1000_continuation import Hot1000ContinuationEngine
from backend.core.cold_reversion import ColdReversionEngine
from backend.core.cold_20_differs import Cold20DiffersEngine


class DSPFXAIPipeline:
    """DSNPFX multi-model digit prediction pipeline.

    Voting models:
    - Frequency
    - Markov
    - Support-aware N-gram sequence

    Research-only diagnostics:
    - First-order TransitionModel (duplicate of Markov, zero vote weight)
    - Statistical digit deviation / entropy
    - X2X pattern detector
    - Cautious 0-9 probability analysis with uncertainty shrinkage
    - Exact 1000-tick hot-digit continuation hypothesis
    - Cold-digit mean-reversion hypotheses over 200/500/1000 ticks
    - Coldest digit over 20 ticks -> one-tick DIGITDIFF hypothesis

    Momentum remains disabled until an independent algorithm is implemented.
    """

    def __init__(
        self,
        digits,
        weights=None,
        prediction_overrides=None,
    ):
        self.digits = [int(digit) for digit in digits]
        self.weights = weights
        self.prediction_overrides = prediction_overrides or {}

        self.analyzer = DigitAnalyzer(self.digits)
        self.markov = MarkovEngine(self.digits)
        self.sequence = SequenceEngine(self.digits)
        self.transition = TransitionModel()
        self.statistics = StatisticalDigitEngine(self.digits)
        self.x2x = X2XResearchEngine(self.digits)
        self.probability_analysis = ProbabilityAnalysisEngine(self.digits)
        self.hot_1000 = Hot1000ContinuationEngine(self.digits)
        self.cold_reversion = ColdReversionEngine(self.digits)
        self.cold_20_differs = Cold20DiffersEngine(self.digits)

        for previous_digit, current_digit in zip(
            self.digits,
            self.digits[1:],
        ):
            self.transition.learn(previous_digit, current_digit)

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

        frequency_result = self.analyzer.predict_next_digit()
        frequency_prediction = (
            frequency_result.get("prediction")
            if frequency_result
            else None
        )

        markov_result = self.markov.predict_next(self.digits[-1])
        markov_prediction = (
            markov_result.get("prediction")
            if markov_result
            else None
        )

        sequence_result = self.sequence.predict(min_support=3)
        sequence_prediction = None
        if sequence_result and sequence_result.get("qualified"):
            sequence_prediction = sequence_result.get("prediction")

        current_digit = self.digits[-1]
        transition_prediction = self.transition.predict(current_digit)
        transition_confidence = self.transition.confidence(current_digit)
        transition_samples = self.transition.samples(current_digit)

        frequency_prediction = self.prediction_overrides.get(
            "frequency", frequency_prediction
        )
        markov_prediction = self.prediction_overrides.get(
            "markov", markov_prediction
        )
        sequence_prediction = self.prediction_overrides.get(
            "sequence", sequence_prediction
        )
        transition_prediction = self.prediction_overrides.get(
            "transition", transition_prediction
        )

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
        result["model_weights"] = decision.weights.copy()

        statistical_report = self.statistics.analyse()
        x2x_report = self.x2x.analyse()
        probability_report = self.probability_analysis.analyse()
        hot_1000_report = self.hot_1000.analyse()
        cold_reversion_report = self.cold_reversion.analyse()
        cold_20_differs_report = self.cold_20_differs.analyse()

        result["model_metadata"] = {
            "frequency": {
                "confidence": (
                    frequency_result.get("confidence", 0.0)
                    if frequency_result else 0.0
                ),
                "strength": (
                    frequency_result.get("strength", "LOW")
                    if frequency_result else "LOW"
                ),
            },
            "markov": {
                "confidence": (
                    markov_result.get("confidence", 0.0)
                    if markov_result else 0.0
                ),
                "probabilities": (
                    markov_result.get("probabilities", {})
                    if markov_result else {}
                ),
            },
            "sequence": {
                "pattern_length": (
                    sequence_result.get("pattern_length")
                    if sequence_result else None
                ),
                "pattern": (
                    sequence_result.get("pattern")
                    if sequence_result else None
                ),
                "confidence": (
                    sequence_result.get("confidence", 0.0)
                    if sequence_result else 0.0
                ),
                "support": (
                    sequence_result.get("support", 0)
                    if sequence_result else 0
                ),
                "minimum_support": (
                    sequence_result.get("minimum_support", 3)
                    if sequence_result else 3
                ),
                "qualified": bool(
                    sequence_result and sequence_result.get("qualified")
                ),
                "matches": (
                    sequence_result.get("matches", {})
                    if sequence_result else {}
                ),
            },
            "transition": {
                "confidence": transition_confidence,
                "samples": transition_samples,
                "probabilities": self.transition.probabilities(current_digit),
                "scope": "RESEARCH_ONLY_DUPLICATE_MARKOV",
            },
            "statistical_deviation": statistical_report,
            "x2x": x2x_report,
            "probability_analysis": probability_report,
            "hot_1000_continuation": hot_1000_report,
            "cold_reversion": cold_reversion_report,
            "cold_20_differs": cold_20_differs_report,
        }

        return result
