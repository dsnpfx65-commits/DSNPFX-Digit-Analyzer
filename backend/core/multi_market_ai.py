from __future__ import annotations

from collections import defaultdict, deque

from backend.core.adaptive_forward_ensemble import get_adaptive_forward_ensemble
from backend.core.ai_pipeline import DSPFXAIPipeline
from backend.core.edge_score import EdgeScoreEngine
from backend.core.market_regime import MarketRegime
from backend.core.precision_prediction_selector import select_precision_candidate
from backend.core.premium_gate import PremiumGate


class MultiMarketAI:
    """Market analyzer with one precision-first, forward-verified prediction path.

    Frequency, Markov, sequence and research models may all generate raw
    candidates for prospective auditing. V10 adaptive forward evidence first
    verifies a candidate digit. V12 then requires an active, independently
    validated conditional edge to confirm that same digit before it can become
    the single DSNPFX published candidate.
    """

    MODELS = ("frequency", "markov", "sequence")

    def __init__(self, market_engine, model_memory):
        self.market_engine = market_engine
        self.model_memory = model_memory
        self.edge_engine = EdgeScoreEngine()
        self.premium_gate = PremiumGate()
        self.adaptive_ensemble = get_adaptive_forward_ensemble()
        self._candidate_history = defaultdict(lambda: deque(maxlen=10))

    @staticmethod
    def _weighted_candidate(predictions, weights):
        """Legacy research vote retained only for diagnostics/auditing."""
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

    @staticmethod
    def _ready_digit(report):
        if not isinstance(report, dict):
            return None
        if str(report.get("status", "")).upper() != "READY":
            return None
        try:
            digit = int(report.get("candidate"))
        except (TypeError, ValueError):
            return None
        return digit if 0 <= digit <= 9 else None

    @staticmethod
    def _adaptive_candidates(raw_predictions, metadata):
        probability = metadata.get("probability_analysis") or {}
        hot = metadata.get("hot_1000_continuation") or {}
        cold = metadata.get("cold_reversion") or {}
        windows = cold.get("windows") or {}
        cold1000 = windows.get(1000) or windows.get("1000") or {}

        return {
            "frequency": raw_predictions.get("frequency"),
            "markov": raw_predictions.get("markov"),
            "sequence": raw_predictions.get("sequence"),
            "probability_best": probability.get("best_match_digit"),
            "hot_1000": MultiMarketAI._ready_digit(hot),
            "cold_1000": MultiMarketAI._ready_digit(cold1000),
        }

    @staticmethod
    def _conservative_confidence(adaptive_decision, precision_decision=None):
        """Use audited forward evidence, never vote share, as confidence."""
        if not adaptive_decision.get("verified_for_use"):
            return 0.0

        snapshot = adaptive_decision.get("snapshot") or {}
        supporters = set(adaptive_decision.get("supporting_models") or [])
        rows = [
            row
            for row in snapshot.get("models", [])
            if row.get("model") in supporters
        ]
        if not rows:
            return 0.0

        conservative = []
        for row in rows:
            try:
                conservative.append(float(row.get("recent_lower_95_pct") or 0.0))
            except (TypeError, ValueError):
                continue
        if not conservative:
            return 0.0

        confidence = min(conservative)
        if precision_decision and precision_decision.get("verified_for_use"):
            try:
                conditional_lower = float(
                    precision_decision.get("validation_lower_95_pct") or 0.0
                )
                if conditional_lower > 0.0:
                    confidence = min(confidence, conditional_lower)
            except (TypeError, ValueError):
                pass
        return round(confidence, 2)

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
                "prediction": None,
                "candidate": None,
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
            metadata = result.get("model_metadata", {})

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

            research_candidate, research_vote_share, research_vote_margin = (
                self._weighted_candidate(active_predictions, active_weights)
            )

            adaptive_candidates = self._adaptive_candidates(raw_predictions, metadata)
            adaptive_decision = self.adaptive_ensemble.choose(
                symbol,
                adaptive_candidates,
            )

            # Build a complete research snapshot using only information that
            # exists before the next tick. The V12 selector compares the current
            # active condition with independently resolved conditional evidence.
            selector_result = {
                "symbol": symbol,
                "regime": regime["regime"],
                "raw_model_predictions": {
                    model: raw_predictions.get(model)
                    for model in self.MODELS
                },
                "model_predictions": active_predictions.copy(),
                "model_metadata": metadata,
            }
            precision_decision = select_precision_candidate(
                selector_result,
                adaptive_decision,
            )

            candidate = (
                precision_decision.get("candidate")
                if precision_decision.get("verified_for_use")
                else None
            )
            confidence = self._conservative_confidence(
                adaptive_decision,
                precision_decision,
            ) if candidate is not None else 0.0
            confidence_margin = (
                float(precision_decision.get("conservative_edge_pp") or 0.0)
                if candidate is not None
                else 0.0
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

            blockers = []
            if not adaptive_decision.get("verified_for_use"):
                blockers.append("No forward-verified adaptive prediction yet")
            elif not precision_decision.get("verified_for_use"):
                blockers.append(
                    "Adaptive digit lacks active independently validated conditional edge"
                )

            blocking_reasons = list(
                dict.fromkeys(
                    blockers
                    + edge.get("blocking_reasons", [])
                    + premium.get("blocking_reasons", [])
                    + (["Bootstrap shadow learning only"] if bootstrap_learning else [])
                )
            )

            return {
                "symbol": symbol,
                "status": "LIVE",
                "prediction": premium["published_prediction"] if candidate is not None else None,
                "candidate": candidate,
                "confidence": confidence,
                "confidence_margin": round(confidence_margin, 2),
                "edge": edge["edge_score"],
                "edge_grade": edge["edge_grade"],
                "edge_components": edge["components"],
                "edge_reasons": edge["reasons"],
                "premium": bool(candidate is not None and premium["is_premium"]),
                "premium_status": premium["status"],
                "blocking_reasons": blocking_reasons,
                "regime": regime["regime"],
                "regime_confidence": regime["confidence"],
                "stability_score": stability_score,
                "prediction_source": "V12_PRECISION_CONDITIONAL_GATE",
                "precision_decision": precision_decision,
                "adaptive_decision": adaptive_decision,
                "adaptive_candidates": adaptive_candidates,
                "research_candidate": research_candidate,
                "research_vote_share_pct": research_vote_share,
                "research_vote_margin_pct": research_vote_margin,
                "model_predictions": active_predictions.copy(),
                "raw_model_predictions": {
                    model: raw_predictions.get(model)
                    for model in self.MODELS
                },
                "model_weights": active_weights.copy(),
                "model_statistics": model_statistics,
                "model_metadata": metadata,
                "bootstrap_learning": bootstrap_learning,
                "active_models": len(active_predictions),
            }

        except Exception as error:
            print(f"AI ERROR {symbol}: {error}")
            return {
                "symbol": symbol,
                "status": "ERROR",
                "prediction": None,
                "candidate": None,
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
