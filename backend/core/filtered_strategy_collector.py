"""Prospective filtered COLD1000 research hypotheses.

These filters do not alter production decisions. They only record a COLD1000
DIGITMATCH candidate when independent telemetry agrees with the same digit.
Every accepted hypothesis is written before the resolving tick and is scored by
the existing StrategyForwardAudit against the 10% baseline and captured Deriv
break-even price.
"""

from __future__ import annotations

from backend.core.proposal_quote_service import get_cached_match_quote
from backend.core.strategy_forward_audit import get_strategy_forward_audit


FILTERED_STRATEGIES = {
    "COLD_1000_MARKOV_AGREE": {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
    "COLD_1000_NGRAM_AGREE": {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
    "COLD_1000_DUAL_MODEL_AGREE": {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
    "COLD_1000_X2X_AGREE": {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
    "COLD_1000_Z196": {"contract_type": "DIGITMATCH", "baseline_pct": 10.0},
}


def register_filtered_strategies() -> None:
    # Importing the shared registry here avoids a second source of truth in the
    # audit engine while keeping the filter implementation isolated.
    from backend.core.strategy_forward_audit import STRATEGIES

    for name, config in FILTERED_STRATEGIES.items():
        STRATEGIES.setdefault(name, dict(config))


register_filtered_strategies()


def _digit(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= 9 else None


def _cold1000_report(metadata: dict) -> dict:
    cold = metadata.get("cold_reversion") or {}
    windows = cold.get("windows") or {}
    return windows.get(1000) or windows.get("1000") or {}


def _stat1000_report(metadata: dict) -> dict:
    statistical = metadata.get("statistical_deviation") or {}
    windows = statistical.get("windows") or {}
    return windows.get(1000) or windows.get("1000") or {}


def filtered_cold1000_candidates(result: dict) -> list[str]:
    """Return filter strategy names whose evidence agrees with COLD1000.

    No condition here is treated as predictive proof. The 1.96 Z threshold is
    the conventional two-sided 95% normal cutoff and is itself only a research
    filter; it must still earn prospective economic edge.
    """
    metadata = result.get("model_metadata") or {}
    cold1000 = _cold1000_report(metadata)
    if str(cold1000.get("status", "")).upper() != "READY":
        return []

    candidate = _digit(cold1000.get("candidate"))
    if candidate is None:
        return []

    model_predictions = result.get("model_predictions") or {}
    markov = _digit(model_predictions.get("markov"))
    sequence = _digit(model_predictions.get("sequence"))

    qualified: list[str] = []

    if markov == candidate:
        qualified.append("COLD_1000_MARKOV_AGREE")

    if sequence == candidate:
        qualified.append("COLD_1000_NGRAM_AGREE")

    if markov == candidate and sequence == candidate:
        qualified.append("COLD_1000_DUAL_MODEL_AGREE")

    x2x = metadata.get("x2x") or {}
    if bool(x2x.get("active")) and _digit(x2x.get("candidate")) == candidate:
        qualified.append("COLD_1000_X2X_AGREE")

    statistical1000 = _stat1000_report(metadata)
    z_scores = statistical1000.get("z_scores") or {}
    z_value = z_scores.get(candidate)
    if z_value is None:
        z_value = z_scores.get(str(candidate))
    try:
        z_value = float(z_value)
    except (TypeError, ValueError):
        z_value = None

    # Because the candidate is the cold digit, only a negative deviation is
    # relevant. -1.96 corresponds to the conventional 95% normal cutoff.
    if z_value is not None and z_value <= -1.96:
        qualified.append("COLD_1000_Z196")

    return qualified


def record_filtered_cold1000(result: dict, source_tick: dict) -> list[str]:
    metadata = result.get("model_metadata") or {}
    cold1000 = _cold1000_report(metadata)
    candidate = _digit(cold1000.get("candidate"))
    symbol = result.get("symbol")

    if not symbol or candidate is None:
        return []

    quote = get_cached_match_quote(symbol, candidate)
    saved: list[str] = []

    for strategy in filtered_cold1000_candidates(result):
        created = get_strategy_forward_audit().create_prediction(
            symbol=symbol,
            strategy=strategy,
            barrier=candidate,
            source_epoch=source_tick["epoch"],
            source_quote=source_tick["quote"],
            historical_rate_pct=cold1000.get("frequency_pct"),
            proposal_quote=quote,
        )
        if created:
            saved.append(strategy)

    return saved
