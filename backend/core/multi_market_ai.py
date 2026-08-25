from __future__ import annotations

from collections import defaultdict, deque

from backend.core.ai_pipeline import DSPFXAIPipeline
from backend.core.edge_score import EdgeScoreEngine
from backend.core.market_regime import MarketRegime
from backend.core.premium_gate import PremiumGate


class MultiMarketAI:
    """Market analyzer with evidence-weighted voting and safe bootstrap learning."""

    # Transition is intentionally excluded from voting because it duplicates
    # first-order Markov. It remains available in model metadata for research.
    MODELS = ("frequency", "markov", "sequence")

    def __init__(self, market_engine, model_memory):
        self.market_engine = market_engine
        self.model_memory = model_memory
        self.edge_engine = EdgeScoreEngine()
        self.premium_gate = PremiumGate()
        self._candidate_history = defaultdict(lambda: deque(maxlen=10))

    @staticmethod
    def _weighted_candidate(predictions, weights):
        votes = {}
        total = 0.0

        for model, prediction in predictions.items():
            if prediction is None:
                continue
            try:
                weight = float(weights.get(model, 0.0) or 0.0)
            except (TypeError, ValueError):
                weight = 0.0
            if weight <= 0.0:
                continue
            digit = int(prediction)
            votes[digit] = votes.get(digit, 0.0) + weight
            total += weight

        if not votes or total <= 0.0:
            return None, 0.0, 0.0

        ranked = sorted(votes.items(), key=lambda item: item[1], reverse=True)
        winner, winner_weight = ranked[0]
        runner_up_weight = ranked[1][1] if len(ranked) > 1 else 0.0
        confidence = winner_weight / total * 100.0
        margin = (winner_weight - runner_up_weight) / total * 100.0
        return winner, round(confidence, 2), round(margin, 2)

    def _stability(self, symbol, candidate):
        history = self._candidate_history[symbol]
        history.append(candidate)

        valid = [value for value in history if value is not None]
        if len(valid) < 2 or candidate is None:
            return 0.0

        matching = sum(value == candidate for value in valid)
        persistence = matching / len(valid) * 100.0

        consecutive = 0
        for value in reversed(valid):
            if value != candidate:
                break
            consecutive += 1

        streak_score = min(100.0, consecutive / 5.0 * 100.0)
        return round(persistence * 0.55 + streak_score * 0.45, 2)

    def analyze(self, symbol):
        digits = self.market_engine.history(symbol)

        if len(digits) < 20:
            return {
                "symbol": symbol,
                "status": "COLLECTING",
                "samples": len(digits),
                "premium": False,
                "edge": 0,
            }

        try:
            regime = MarketRegime(digits).analyse()
            adaptive_weights = self.model_memory.adaptive_weights(symbol=symbol)
            earned_weight_total = sum(
                max(0.0, float(adaptive_weights.get(model, 0.0) or 0.0))
                for model in self.MODELS
            )

            # Bootstrap solves the zero-evidence deadlock: equal default voting
            # is allowed only to generate shadow-learning candidates. Edge and
            # production gates still see zero historical evidence, so these
            # candidates cannot become production signals prematurely.
            bootstrap_learning = earned_weight_total <= 0.0
            pipeline = DSPFXAIPipeline(
                digits,
                weights=None if bootstrap_learning else adaptive_weights,
            )
            result = pipeline.run()

            if not result:
                raise RuntimeError("AI pipeline returned no result")

            raw_predictions = result.get("model_predictions", {})
            used_weights = result.get("model_weights", {})

            active_predictions = {}
            active_weights = {}

            for model in self.MODELS:
                prediction = raw_predictions.get(model)
                try:
                    weight = float(used_weights.get(model, 0.0) or 0.0)
                except (TypeError, ValueError):
                    weight = 0.0

                if prediction is None or weight <= 0.0:
                    continue

                stats = self.model_memory.statistics(model, symbol=symbol)
                if not bootstrap_learning and stats.get("status") == "SUSPENDED":
                    continue

                active_predictions[model] = int(prediction)
                active_weights[model] = weight

            candidate, confidence, confidence_margin = self._weighted_candidate(
                active_predictions,
                active_weights,
            )
            stability_score = self._stability(symbol, candidate)

            model_statistics = {
                model: self.model_memory.statistics(model, symbol=symbol)
                for model in self.MODELS
            }

            edge = self.edge_engine.calculate(
                model_statistics=model_statistics,
                model_predictions=active_predictions,
                model_weights=active_weights,
                candidate_prediction=candidate,
                regime_confidence=regime["confidence"],
                stability_score=stability_score,
            )

            premium = self.premium_gate.evaluate(
                candidate_prediction=candidate,
                edge_result=edge,
            )

            blocking_reasons = list(
                dict.fromkeys(
                    edge.get("blocking_reasons", [])
                    + premium.get("blocking_reasons", [])
                    + (["Bootstrap shadow learning only"] if bootstrap_learning else [])
                )
            )

            return {
                "symbol": symbol,
                "status": "LIVE",
                "prediction": premium["published_prediction"],
                "candidate": candidate,
                "confidence": confidence,
                "confidence_margin": confidence_margin,
                "edge": edge["edge_score"],
                "edge_grade": edge["edge_grade"],
                "edge_components": edge["components"],
                "edge_reasons": edge["reasons"],
                "premium": premium["is_premium"] and not bootstrap_learning,
                "premium_status": premium["status"],
                "blocking_reasons": blocking_reasons,
                "regime": regime["regime"],
                "regime_confidence": regime["confidence"],
                "stability_score": stability_score,
                "model_predictions": active_predictions.copy(),
                "model_weights": active_weights.copy(),
                "model_statistics": model_statistics,
                "model_metadata": result.get("model_metadata", {}),
                "bootstrap_learning": bootstrap_learning,
                "active_models": len(active_predictions),
            }

        except Exception as error:
            print(f"AI ERROR {symbol}: {error}")
            return {
                "symbol": symbol,
                "status": "ERROR",
                "premium": False,
                "edge": 0,
                "error": str(error),
            }

    def scan(self):
        results = [
            self.analyze(symbol)
            for symbol in list(self.market_engine.markets)
        ]
        return sorted(
            results,
            key=lambda item: item.get("edge", 0),
            reverse=True,
        )
