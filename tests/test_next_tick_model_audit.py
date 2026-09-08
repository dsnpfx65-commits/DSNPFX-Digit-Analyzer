"""Validation for the DSNPFX exact-next-tick model audit.

The adaptive forward ensemble is the authoritative prospective audit store.
These tests prove that every available model is committed before settlement,
that the next later tick resolves each model independently, and that statistics
remain separated by market/model.
"""

from backend.core.adaptive_forward_ensemble import AdaptiveForwardEnsemble, MODEL_KEYS


def test_all_available_models_are_committed_before_next_tick(tmp_path, monkeypatch):
    database = tmp_path / "audit.db"
    audit = AdaptiveForwardEnsemble(str(database))

    monkeypatch.setattr(
        "backend.core.adaptive_forward_ensemble.get_cached_match_quote",
        lambda symbol, digit: {"break_even_probability_pct": 11.2},
    )

    result = {
        "symbol": "R_100",
        "raw_model_predictions": {
            "frequency": 1,
            "markov": 2,
            "sequence": 3,
        },
        "model_metadata": {
            "probability_analysis": {"best_match_digit": 4},
            "hot_1000_continuation": {"status": "READY", "candidate": 5},
            "cold_reversion": {
                "windows": {1000: {"status": "READY", "candidate": 6}}
            },
        },
    }
    source_tick = {"epoch": 100, "quote": "123.40"}

    assert audit.create_from_result(result, source_tick) == len(MODEL_KEYS)

    pending = audit.connection.execute(
        "SELECT model, prediction, source_epoch, result "
        "FROM adaptive_forward_predictions ORDER BY model"
    ).fetchall()
    assert len(pending) == len(MODEL_KEYS)
    assert {row["model"] for row in pending} == set(MODEL_KEYS)
    assert all(row["source_epoch"] == 100 for row in pending)
    assert all(row["result"] is None for row in pending)

    # Same source tick cannot be counted as the outcome.
    assert audit.resolve("R_100", 1, tick_epoch=100, tick_quote="123.41") == []

    resolved = audit.resolve("R_100", 4, tick_epoch=101, tick_quote="123.44")
    assert len(resolved) == len(MODEL_KEYS)
    outcomes = {row["model"]: row["result"] for row in resolved}
    assert outcomes["probability_best"] == "WIN"
    assert all(
        outcome == "LOSS"
        for model, outcome in outcomes.items()
        if model != "probability_best"
    )

    audit.close()


def test_statistics_are_per_market_and_per_model(tmp_path):
    database = tmp_path / "audit.db"
    audit = AdaptiveForwardEnsemble(str(database))

    for epoch in range(1, 6):
        assert audit.create_prediction(
            symbol="R_75",
            model="frequency",
            prediction=7,
            source_epoch=epoch * 2,
            source_quote=f"100.{epoch}0",
            break_even_probability_pct=11.2,
        )
        audit.resolve(
            "R_75",
            7 if epoch <= 2 else 3,
            tick_epoch=epoch * 2 + 1,
            tick_quote=f"100.{epoch}7",
        )

    stats = audit.statistics("R_75", "frequency")
    assert stats["resolved"] == 5
    assert stats["wins"] == 2
    assert stats["losses"] == 3
    assert stats["accuracy_pct"] == 40.0

    untouched = audit.statistics("R_100", "frequency")
    assert untouched["resolved"] == 0

    audit.close()
