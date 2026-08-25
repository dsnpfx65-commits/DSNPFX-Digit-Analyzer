"""DSNPFX Intelligence V5 auditable edge score."""

from __future__ import annotations

import math
from typing import Any


class EdgeScoreEngine:
    RANDOM_BASELINE = 10.0

    COMPONENT_WEIGHTS = {
        "historical_edge": 0.20,
        "recent_edge": 0.30,
        "agreement": 0.20,
        "regime_quality": 0.08,
        "sample_reliability": 0.10,
        "prediction_stability": 0.12,
    }

    def calculate(
        self,
        *,
        model_statistics: dict[str, dict[str, Any]],
        model_predictions: dict[str, int | None],
        model_weights: dict[str, float],
        candidate_prediction: int | None,
        regime_confidence: float,
        stability_score: float = 0.0,
    ) -> dict[str, Any]:
        active_models = {
            model: prediction
            for model, prediction in model_predictions.items()
            if (
                prediction is not None
                and self._number(model_weights.get(model)) > 0.0
            )
        }

        historical_edge = self._historical_edge(
            model_statistics, model_weights, active_models
        )
        recent_edge = self._recent_edge(
            model_statistics, model_weights, active_models
        )
        agreement = self._agreement_score(
            active_models, model_weights, candidate_prediction
        )
        regime_quality = self._clamp(regime_confidence)
        sample_reliability = self._sample_reliability(
            model_statistics, active_models
        )
        prediction_stability = self._clamp(stability_score)

        components = {
            "historical_edge": round(historical_edge, 2),
            "recent_edge": round(recent_edge, 2),
            "agreement": round(agreement, 2),
            "regime_quality": round(regime_quality, 2),
            "sample_reliability": round(sample_reliability, 2),
            "prediction_stability": round(prediction_stability, 2),
        }

        raw_score = sum(
            components[name] * weight
            for name, weight in self.COMPONENT_WEIGHTS.items()
        )
        evidence_cap = self._evidence_cap(
            historical_edge=historical_edge,
            recent_edge=recent_edge,
            sample_reliability=sample_reliability,
            active_model_count=len(active_models),
            stability=prediction_stability,
        )
        edge_score = min(raw_score, evidence_cap)

        return {
            "edge_score": round(self._clamp(edge_score), 2),
            "edge_grade": self._grade(edge_score),
            "components": components,
            "active_models": len(active_models),
            "evidence_cap": round(evidence_cap, 2),
            "reasons": self._positive_reasons(components),
            "blocking_reasons": self._blocking_reasons(
                components=components,
                active_model_count=len(active_models),
                candidate_prediction=candidate_prediction,
            ),
        }

    def _historical_edge(self, stats, weights, active) -> float:
        values = []
        for model in active:
            item = stats.get(model, {})
            samples = self._first_number(
                item, ("lifetime_samples", "samples")
            )
            if samples <= 0:
                continue
            accuracy = self._first_number(
                item, ("lifetime_accuracy", "accuracy")
            )
            edge = max(0.0, accuracy - self.RANDOM_BASELINE)
            values.append((
                self._clamp(edge / 5.0 * 100.0),
                self._number(weights.get(model)),
            ))
        return self._weighted_average(values)

    def _recent_edge(self, stats, weights, active) -> float:
        values = []
        for model in active:
            item = stats.get(model, {})
            recent_samples = self._first_number(
                item,
                (
                    "recent_samples",
                    "last100_samples",
                    "last50_samples",
                    "last20_samples",
                ),
            )
            if recent_samples <= 0:
                continue
            recent_accuracy = self._first_number(
                item,
                ("recent_accuracy", "last100", "last50", "last20"),
            )
            edge = max(0.0, recent_accuracy - self.RANDOM_BASELINE)
            values.append((
                self._clamp(edge / 5.0 * 100.0),
                self._number(weights.get(model)),
            ))
        return self._weighted_average(values)

    def _agreement_score(self, predictions, weights, candidate) -> float:
        if candidate is None:
            return 0.0
        total = 0.0
        agreeing = 0.0
        for model, prediction in predictions.items():
            weight = self._number(weights.get(model))
            if weight <= 0.0:
                continue
            total += weight
            if prediction == candidate:
                agreeing += weight
        return self._clamp(agreeing / total * 100.0) if total > 0 else 0.0

    def _sample_reliability(self, stats, active) -> float:
        samples = []
        for model in active:
            count = self._first_number(
                stats.get(model, {}),
                ("recent_samples", "last100_samples"),
            )
            if count > 0:
                samples.append(count)
        if not samples:
            return 0.0
        average = sum(samples) / len(samples)
        return self._clamp(average / 100.0 * 100.0)

    @staticmethod
    def _evidence_cap(
        *,
        historical_edge: float,
        recent_edge: float,
        sample_reliability: float,
        active_model_count: int,
        stability: float,
    ) -> float:
        if active_model_count < 2:
            return 25.0
        if recent_edge <= 0.0:
            return 35.0
        if recent_edge < 20.0:
            return 50.0
        if historical_edge < 10.0:
            return 55.0
        if sample_reliability < 30.0:
            return 60.0
        if stability < 60.0:
            return 65.0
        return 100.0

    @staticmethod
    def _positive_reasons(c):
        reasons = []
        if c["historical_edge"] >= 35:
            reasons.append("Strong historical statistical edge")
        if c["recent_edge"] >= 35:
            reasons.append("Recent performance is above baseline")
        if c["agreement"] >= 66:
            reasons.append("Strong weighted model agreement")
        if c["prediction_stability"] >= 70:
            reasons.append("Candidate is stable across scans")
        return reasons

    @staticmethod
    def _blocking_reasons(*, components, active_model_count, candidate_prediction):
        reasons = []
        if candidate_prediction is None:
            reasons.append("No candidate prediction available")
        if active_model_count < 2:
            reasons.append("Fewer than two eligible active models")
        if components["historical_edge"] < 20:
            reasons.append("Historical edge is not strong enough")
        if components["recent_edge"] < 20:
            reasons.append("Recent performance lacks verified evidence")
        if components["agreement"] < 60:
            reasons.append("Weighted model agreement is too weak")
        if components["sample_reliability"] < 30:
            reasons.append("Insufficient recent model samples")
        if components["prediction_stability"] < 60:
            reasons.append("Candidate prediction is unstable")
        return reasons

    @staticmethod
    def _grade(score):
        if score >= 85:
            return "ELITE"
        if score >= 75:
            return "PREMIUM"
        if score >= 65:
            return "STRONG"
        if score >= 50:
            return "WATCH"
        return "NO EDGE"

    @staticmethod
    def _weighted_average(values):
        filtered = [(v, w) for v, w in values if w > 0]
        if not filtered:
            return 0.0
        total = sum(w for _, w in filtered)
        return sum(v * w for v, w in filtered) / total

    @staticmethod
    def _first_number(values, keys):
        for key in keys:
            if key in values:
                return EdgeScoreEngine._number(values[key])
        return 0.0

    @staticmethod
    def _number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _clamp(value):
        return max(0.0, min(100.0, float(value)))
