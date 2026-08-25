"""DSNPFX research-only next-digit probability analysis.

This module estimates a 0-9 next-digit distribution from several simple,
auditable models. It is deliberately isolated from the production publication
gate: the output is research telemetry, not a calibrated win probability and
not permission to place a trade.

The engine combines:
- long-window frequency
- first-order Markov conditional frequency
- support-aware 2-5 digit N-gram context
- short-window recency frequency

All component distributions use Dirichlet/Laplace smoothing and are shrunk
toward the 10% exact-digit baseline when support is weak. This prevents tiny
samples from producing extreme-looking percentages.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from backend.core.sequence_engine import SequenceEngine


@dataclass(frozen=True)
class _Component:
    name: str
    distribution: dict[int, float]
    support: int
    reliability: float
    base_weight: float


class ProbabilityAnalysisEngine:
    """Produce cautious research estimates for the next displayed digit."""

    BASELINE = 0.10
    WINDOWS = (50, 200, 500, 1000)
    BASE_WEIGHTS = {
        "frequency": 0.35,
        "markov": 0.35,
        "sequence": 0.20,
        "recency": 0.10,
    }

    def __init__(self, digits):
        self.digits = [int(digit) for digit in digits]
        for digit in self.digits:
            if not 0 <= digit <= 9:
                raise ValueError("Every digit must be between 0 and 9")

    @staticmethod
    def _smoothed_distribution(
        counts: Mapping[int, int],
        *,
        alpha: float = 1.0,
    ) -> dict[int, float]:
        """Return a 0-1 probability distribution with symmetric smoothing."""
        alpha = max(0.0, float(alpha))
        total = sum(max(0, int(counts.get(digit, 0))) for digit in range(10))
        denominator = total + alpha * 10.0

        if denominator <= 0.0:
            return {digit: 0.10 for digit in range(10)}

        return {
            digit: (max(0, int(counts.get(digit, 0))) + alpha) / denominator
            for digit in range(10)
        }

    @staticmethod
    def _percent_distribution(distribution: Mapping[int, float]) -> dict[int, float]:
        return {
            digit: round(float(distribution.get(digit, 0.0)) * 100.0, 4)
            for digit in range(10)
        }

    @staticmethod
    def _reliability(support: int, target: int) -> float:
        if target <= 0:
            return 1.0
        return max(0.0, min(1.0, int(support) / float(target)))

    def _frequency_component(self) -> _Component:
        sample = self.digits[-1000:]
        counts = Counter(sample)
        return _Component(
            name="frequency",
            distribution=self._smoothed_distribution(counts, alpha=1.0),
            support=len(sample),
            reliability=self._reliability(len(sample), 200),
            base_weight=self.BASE_WEIGHTS["frequency"],
        )

    def _recency_component(self) -> _Component:
        sample = self.digits[-50:]
        counts = Counter(sample)
        return _Component(
            name="recency",
            distribution=self._smoothed_distribution(counts, alpha=2.0),
            support=len(sample),
            reliability=self._reliability(len(sample), 100),
            base_weight=self.BASE_WEIGHTS["recency"],
        )

    def _markov_component(self) -> _Component:
        if len(self.digits) < 2:
            return _Component(
                name="markov",
                distribution={digit: 0.10 for digit in range(10)},
                support=0,
                reliability=0.0,
                base_weight=self.BASE_WEIGHTS["markov"],
            )

        current = self.digits[-1]
        transitions = Counter()
        history = self.digits[-1000:]
        for previous, following in zip(history, history[1:]):
            if previous == current:
                transitions[following] += 1

        support = sum(transitions.values())
        return _Component(
            name="markov",
            distribution=self._smoothed_distribution(transitions, alpha=1.0),
            support=support,
            reliability=self._reliability(support, 50),
            base_weight=self.BASE_WEIGHTS["markov"],
        )

    def _sequence_component(self) -> tuple[_Component, dict]:
        result = SequenceEngine(self.digits[-1000:]).predict(min_support=3)

        if not result or not result.get("qualified"):
            metadata = dict(result or {})
            return (
                _Component(
                    name="sequence",
                    distribution={digit: 0.10 for digit in range(10)},
                    support=int(metadata.get("support", 0) or 0),
                    reliability=0.0,
                    base_weight=self.BASE_WEIGHTS["sequence"],
                ),
                metadata,
            )

        matches = {
            int(digit): int(count)
            for digit, count in (result.get("matches") or {}).items()
        }
        support = int(result.get("support", 0) or 0)
        component = _Component(
            name="sequence",
            distribution=self._smoothed_distribution(matches, alpha=1.0),
            support=support,
            reliability=self._reliability(support, 20),
            base_weight=self.BASE_WEIGHTS["sequence"],
        )
        return component, dict(result)

    def _window_reports(self) -> dict[int, dict]:
        reports: dict[int, dict] = {}
        for window in self.WINDOWS:
            sample = self.digits[-window:]
            if not sample:
                continue
            counts = Counter(sample)
            reports[window] = {
                "window": window,
                "samples": len(sample),
                "percentages": self._percent_distribution(
                    self._smoothed_distribution(counts, alpha=1.0)
                ),
            }
        return reports

    def analyse(self, break_even_probability_pct: float | None = None) -> dict:
        if len(self.digits) < 20:
            return {
                "status": "INSUFFICIENT_DATA",
                "scope": "RESEARCH_ONLY",
                "calibrated": False,
                "baseline_probability_pct": 10.0,
                "samples": len(self.digits),
                "best_match_digit": None,
                "best_match_estimate_pct": None,
                "digit_probabilities_pct": {},
                "research_action": "NO_TRADE",
            }

        frequency = self._frequency_component()
        markov = self._markov_component()
        sequence, sequence_metadata = self._sequence_component()
        recency = self._recency_component()
        components = (frequency, markov, sequence, recency)

        effective_weights = {
            component.name: component.base_weight * component.reliability
            for component in components
        }
        effective_total = sum(effective_weights.values())

        if effective_total <= 0.0:
            raw = {digit: self.BASELINE for digit in range(10)}
        else:
            raw = {}
            for digit in range(10):
                raw[digit] = sum(
                    component.distribution[digit]
                    * effective_weights[component.name]
                    for component in components
                ) / effective_total

        max_possible = sum(component.base_weight for component in components)
        evidence_reliability = (
            min(1.0, effective_total / max_possible)
            if max_possible > 0.0
            else 0.0
        )

        # Shrink the raw model blend toward the 10% null expectation whenever
        # support is incomplete. This is an uncertainty control, not calibration.
        final = {
            digit: self.BASELINE
            + evidence_reliability * (raw[digit] - self.BASELINE)
            for digit in range(10)
        }

        # Renormalize defensively after floating-point arithmetic.
        total_probability = sum(final.values())
        if total_probability > 0:
            final = {
                digit: probability / total_probability
                for digit, probability in final.items()
            }

        best_match_digit = max(final, key=lambda digit: (final[digit], -digit))
        coldest_digit = min(final, key=lambda digit: (final[digit], digit))
        best_match_pct = final[best_match_digit] * 100.0
        best_differ_pct = (1.0 - final[coldest_digit]) * 100.0
        baseline_edge_pp = best_match_pct - 10.0

        break_even = None
        payout_edge_pp = None
        if break_even_probability_pct is not None:
            try:
                break_even = float(break_even_probability_pct)
            except (TypeError, ValueError):
                break_even = None
            if break_even is not None:
                break_even = max(0.0, min(100.0, break_even))
                payout_edge_pp = best_match_pct - break_even

        active_components = sum(
            component.reliability > 0.0
            for component in components
        )
        if (
            len(self.digits) >= 200
            and evidence_reliability >= 0.50
            and baseline_edge_pp >= 2.0
            and active_components >= 2
        ):
            research_action = "WATCH"
        else:
            research_action = "NO_TRADE"

        raw_top_pct = raw[best_match_digit] * 100.0
        uncertainty_penalty_pp = max(0.0, raw_top_pct - best_match_pct)

        return {
            "status": "READY",
            "scope": "RESEARCH_ONLY",
            "calibrated": False,
            "warning": (
                "Model estimate only; production confidence must come from "
                "prospective resolved outcomes and calibration."
            ),
            "samples": len(self.digits),
            "baseline_probability_pct": 10.0,
            "digit_probabilities_pct": self._percent_distribution(final),
            "best_match_digit": int(best_match_digit),
            "best_match_estimate_pct": round(best_match_pct, 4),
            "best_match_edge_vs_baseline_pp": round(baseline_edge_pp, 4),
            "best_differ_barrier": int(coldest_digit),
            "best_differ_estimate_pct": round(best_differ_pct, 4),
            "break_even_probability_pct": (
                round(break_even, 4) if break_even is not None else None
            ),
            "estimated_edge_vs_break_even_pp": (
                round(payout_edge_pp, 4) if payout_edge_pp is not None else None
            ),
            "research_reliability_pct": round(evidence_reliability * 100.0, 2),
            "uncertainty_penalty_pp": round(uncertainty_penalty_pp, 4),
            "active_components": active_components,
            "research_action": research_action,
            "component_weights": {
                component.name: round(effective_weights[component.name], 6)
                for component in components
            },
            "component_support": {
                component.name: int(component.support)
                for component in components
            },
            "component_reliability_pct": {
                component.name: round(component.reliability * 100.0, 2)
                for component in components
            },
            "component_probabilities_pct": {
                component.name: self._percent_distribution(component.distribution)
                for component in components
            },
            "sequence_context": sequence_metadata,
            "windows": self._window_reports(),
        }
