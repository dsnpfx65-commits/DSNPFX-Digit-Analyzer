from backend.core.conditional_forward_discovery import ConditionalForwardDiscovery


def _result(symbol="R_100", digit=4, regime="TRENDING"):
    return {
        "symbol": symbol,
        "regime": regime,
        "raw_model_predictions": {
            "frequency": digit,
            "markov": digit,
            "sequence": digit,
        },
        "model_metadata": {
            "sequence": {"support": 8},
            "statistical_deviation": {
                "entropy_normalised": 98.0,
                "max_abs_z": 2.8,
            },
            "probability_analysis": {"best_match_digit": digit},
            "hot_1000_continuation": {"status": "READY", "candidate": digit},
            "cold_reversion": {
                "windows": {1000: {"status": "READY", "candidate": digit}}
            },
        },
    }


def test_conditions_are_committed_before_strictly_later_tick(tmp_path, monkeypatch):
    audit = ConditionalForwardDiscovery(str(tmp_path / "conditional.db"))
    monkeypatch.setattr(
        "backend.core.conditional_forward_discovery.get_cached_match_quote",
        lambda symbol, digit: {"break_even_probability_pct": 11.2},
    )

    saved = audit.create_from_result(
        _result(),
        {"epoch": 101, "quote": "100.04"},
    )
    assert saved > 0

    # A prediction can never resolve against its own source tick.
    assert audit.resolve("R_100", 4, tick_epoch=101, tick_quote="100.04") == 0
    assert audit.resolve("R_100", 4, tick_epoch=102, tick_quote="100.04") == saved

    rows = audit.connection.execute(
        "SELECT DISTINCT result, actual, resolved_epoch FROM conditional_predictions"
    ).fetchall()
    assert {row["result"] for row in rows} == {"WIN"}
    assert {row["actual"] for row in rows} == {4}
    assert {row["resolved_epoch"] for row in rows} == {102}
    audit.close()


def test_partition_is_fixed_from_source_epoch(tmp_path, monkeypatch):
    audit = ConditionalForwardDiscovery(str(tmp_path / "conditional.db"))
    monkeypatch.setattr(
        "backend.core.conditional_forward_discovery.get_cached_match_quote",
        lambda symbol, digit: {"break_even_probability_pct": 11.2},
    )

    audit.create_from_result(_result(), {"epoch": 104, "quote": "1"})
    audit.resolve("R_100", 4, tick_epoch=105, tick_quote="2")
    discovery = audit.connection.execute(
        "SELECT DISTINCT partition FROM conditional_predictions"
    ).fetchall()
    assert {row["partition"] for row in discovery} == {"DISCOVERY"}

    audit.create_from_result(_result(), {"epoch": 105, "quote": "2"})
    audit.resolve("R_100", 4, tick_epoch=106, tick_quote="3")
    partitions = audit.connection.execute(
        "SELECT DISTINCT partition FROM conditional_predictions"
    ).fetchall()
    assert {row["partition"] for row in partitions} == {"DISCOVERY", "VALIDATION"}
    audit.close()


def test_validation_edge_requires_discovery_and_holdout_evidence(tmp_path):
    audit = ConditionalForwardDiscovery(str(tmp_path / "conditional.db"))

    # Seed one predefined condition directly so the test can exercise the
    # evidence rules without requiring hundreds of live scan cycles.
    for index in range(400):
        partition = "VALIDATION" if index < 120 else "DISCOVERY"
        win = index < 120 or index < 260
        audit.connection.execute(
            """
            INSERT INTO conditional_predictions(
                created_at, resolved_at, symbol, model, prediction,
                condition_family, condition_value, partition,
                source_epoch, source_quote, break_even_probability_pct,
                actual, resolved_epoch, resolved_quote, result
            ) VALUES('x','y','R_75','frequency',7,'REGIME','TRENDING',?,?,?,?,?,?,?,?)
            """,
            (
                partition,
                index * 2 + 1,
                "1",
                11.2,
                7 if win else 3,
                index * 2 + 2,
                "2",
                "WIN" if win else "LOSS",
            ),
        )
    audit.connection.commit()

    rows = audit.leaderboard("R_75")
    assert len(rows) == 1
    row = rows[0]
    assert row["discovery"]["resolved"] >= 200
    assert row["validation"]["resolved"] >= 100
    assert row["discovery_promising"] is True
    assert row["validation_economic_edge"] is True
    assert row["status"] == "VALIDATION EDGE"
    audit.close()
