"""Install filtered COLD1000 research recording beside the V9 collector."""

from __future__ import annotations

from backend.core.filtered_strategy_collector import record_filtered_cold1000


def install(v9_module) -> None:
    if getattr(v9_module, "_DSNPFX_FILTERED_STRATEGIES_INSTALLED", False):
        return

    original = v9_module._record_independent_strategies

    def record_with_filters(result: dict, source_tick: dict) -> None:
        # Preserve all existing unfiltered research first.
        original(result, source_tick)
        # Then record only filtered COLD1000 hypotheses whose independent
        # telemetry agrees with the exact same digit before the next tick.
        record_filtered_cold1000(result, source_tick)

    v9_module._record_independent_strategies = record_with_filters
    v9_module._DSNPFX_FILTERED_STRATEGIES_INSTALLED = True
