"""DSNPFX Intelligence V5 premium opportunity gate."""

from __future__ import annotations

from typing import Any


class PremiumGate:
    """Publish only opportunities supported by genuine recent evidence."""

    def __init__(
        self,
        min_edge_score: float = 65.0,
        min_historical_edge: float = 20.0,
        min_recent_edge: float = 25.0,
        min_agreement: float = 66.0,
        min_sample_reliability: float = 30.0,
        min_prediction_stability: float = 60.0,
        min_active_models: int = 2,
    ):
        self.min_edge_score = min_edge_score
        self.min_historical_edge = min_historical_edge
        self.min_recent_edge = min_recent_edge
        self.min_agreement = min_agreement
        self.min_sample_reliability = min_sample_reliability
        self.min_prediction_stability = min_prediction_stability
        self.min_active_models = min_active_models

    def evaluate(
        self,
        *,
        candidate_prediction: int | None,
        edge_result: dict[str, Any],
    ) -> dict[str, Any]:
        c = edge_result.get("components", {})
        active_models = int(edge_result.get("active_models", 0))
        edge_score = float(edge_result.get("edge_score", 0.0))
        blockers = []

        if candidate_prediction is None:
            blockers.append("No candidate digit available")
        if edge_score < self.min_edge_score:
            blockers.append(f"Edge Score below {self.min_edge_score:.0f}")
        if float(c.get("historical_edge", 0.0)) < self.min_historical_edge:
            blockers.append("Historical edge below premium threshold")
        if float(c.get("recent_edge", 0.0)) < self.min_recent_edge:
            blockers.append("Recent edge below premium threshold")
        if float(c.get("agreement", 0.0)) < self.min_agreement:
            blockers.append("Model agreement below premium threshold")
        if float(c.get("sample_reliability", 0.0)) < self.min_sample_reliability:
            blockers.append("Sample reliability below premium threshold")
        if float(c.get("prediction_stability", 0.0)) < self.min_prediction_stability:
            blockers.append("Prediction stability below premium threshold")
        if active_models < self.min_active_models:
            blockers.append("Not enough eligible active models")

        is_premium = not blockers
        return {
            "is_premium": is_premium,
            "status": (
                "PREMIUM OPPORTUNITY"
                if is_premium
                else "NO PREMIUM OPPORTUNITY"
            ),
            "published_prediction": candidate_prediction if is_premium else None,
            "blocking_reasons": blockers,
        }
