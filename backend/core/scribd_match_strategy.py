"""Research-only implementation of the Scribd Digit Match rules.

Source hypothesis: https://www.scribd.com/document/798755023/MATCHES

The document describes visual percentage/bar/cursor conditions. Raw Deriv ticks do
not expose the Digit Circle UI's green/red bars, so this module operationalizes a
bar reproducibly as the direction of a digit's percentage between two adjacent
short windows. A small percentage-point change is treated as NEUTRAL.

Nothing in this module publishes a production signal or places a trade. It only
creates a deterministic hypothesis that can be prospectively audited.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class MatchRule:
    target: int
    below_10: tuple[int, ...]
    entry_cursor: int
    stable_digits: tuple[int, ...]
    at_least_below_10: int | None = None


RULES: dict[int, MatchRule] = {
    0: MatchRule(0, tuple(range(1, 10)), 2, (1, 2), at_least_below_10=3),
    1: MatchRule(1, (0, 2, 3), 3, (2, 3)),
    2: MatchRule(2, (0, 1, 3, 4), 4, (1, 3, 4)),
    3: MatchRule(3, (0, 1, 2, 4), 2, (2, 4)),
    4: MatchRule(4, (0, 1, 2, 3), 4, (2, 3)),
    5: MatchRule(5, (0, 1, 2, 3, 4), 2, (3, 4)),
    6: MatchRule(6, (0, 1, 2, 3, 5), 2, (4, 5)),
    7: MatchRule(7, (0, 1, 2, 3, 4, 5), 4, (5, 6)),
    8: MatchRule(8, (0, 1, 2, 3, 4, 6), 2, (6, 7)),
    9: MatchRule(9, (0, 1, 2, 3, 4, 5, 6), 4, (6, 7, 8)),
}


def _percentages(values: Iterable[int]) -> dict[int, float]:
    sample = [int(v) for v in values]
    if not sample:
        return {digit: 0.0 for digit in range(10)}
    counts = Counter(sample)
    total = float(len(sample))
    return {digit: counts.get(digit, 0) / total * 100.0 for digit in range(10)}


def _trend_deltas(digits: list[int], trend_window: int) -> dict[int, float]:
    if trend_window < 1 or len(digits) < trend_window * 2:
        return {digit: 0.0 for digit in range(10)}
    previous = _percentages(digits[-2 * trend_window : -trend_window])
    recent = _percentages(digits[-trend_window:])
    return {digit: recent[digit] - previous[digit] for digit in range(10)}


def evaluate_snapshot(
    *,
    percentages: dict[int, float],
    trend_delta_pp: dict[int, float],
    cursor_digit: int,
    target_neutral_tolerance_pp: float = 1.0,
    stable_tolerance_pp: float = 2.0,
) -> dict[int, dict]:
    """Evaluate every rule from an already-computed market snapshot."""
    reports: dict[int, dict] = {}

    for target, rule in RULES.items():
        below_flags = {digit: percentages.get(digit, 0.0) < 10.0 for digit in rule.below_10}
        if rule.at_least_below_10 is None:
            percentage_gate = all(below_flags.values())
        else:
            percentage_gate = sum(below_flags.values()) >= rule.at_least_below_10

        target_delta = float(trend_delta_pp.get(target, 0.0))
        target_neutral = abs(target_delta) <= target_neutral_tolerance_pp

        stable = {
            digit: abs(float(trend_delta_pp.get(digit, 0.0))) <= stable_tolerance_pp
            for digit in rule.stable_digits
        }
        stability_gate = all(stable.values())
        cursor_gate = int(cursor_digit) == rule.entry_cursor

        ready = percentage_gate and target_neutral and stability_gate and cursor_gate

        reports[target] = {
            "status": "READY" if ready else "WAITING",
            "candidate": target,
            "entry_cursor": rule.entry_cursor,
            "cursor_digit": int(cursor_digit),
            "percentage_gate": percentage_gate,
            "target_neutral": target_neutral,
            "stability_gate": stability_gate,
            "cursor_gate": cursor_gate,
            "required_below_10": list(rule.below_10),
            "required_below_10_count": rule.at_least_below_10,
            "below_10_flags": below_flags,
            "stable_digits": list(rule.stable_digits),
            "stable_flags": stable,
            "target_trend_delta_pp": round(target_delta, 4),
        }

    return reports


def analyze_scribd_match(
    digits: Iterable[int],
    *,
    frequency_window: int = 100,
    trend_window: int = 20,
    target_neutral_tolerance_pp: float = 1.0,
    stable_tolerance_pp: float = 2.0,
) -> dict:
    sample = [int(v) for v in digits if 0 <= int(v) <= 9]
    minimum = max(frequency_window, trend_window * 2)
    if len(sample) < minimum:
        return {
            "status": "COLLECTING",
            "samples": len(sample),
            "minimum_samples": minimum,
            "ready_targets": [],
            "rules": {},
        }

    frequency_sample = sample[-frequency_window:]
    percentages = _percentages(frequency_sample)
    deltas = _trend_deltas(sample, trend_window)
    cursor = sample[-1]
    reports = evaluate_snapshot(
        percentages=percentages,
        trend_delta_pp=deltas,
        cursor_digit=cursor,
        target_neutral_tolerance_pp=target_neutral_tolerance_pp,
        stable_tolerance_pp=stable_tolerance_pp,
    )
    ready_targets = [target for target, report in reports.items() if report["status"] == "READY"]

    return {
        "status": "READY" if ready_targets else "WAITING",
        "samples": len(sample),
        "frequency_window": frequency_window,
        "trend_window": trend_window,
        "cursor_digit": cursor,
        "percentages": {digit: round(value, 4) for digit, value in percentages.items()},
        "trend_delta_pp": {digit: round(value, 4) for digit, value in deltas.items()},
        "ready_targets": ready_targets,
        "rules": reports,
        "scope": "RESEARCH_ONLY",
        "bar_proxy": "adjacent short-window percentage direction",
    }
