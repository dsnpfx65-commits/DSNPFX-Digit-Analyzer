from backend.core.precision_prediction_selector import select_precision_candidate


def _result():
    return {
        "symbol": "R_100",
        "regime": "RANDOM",
        "raw_model_predictions": {
            "frequency": 7,
            "markov": 7,
            "sequence": 2,
        },
        "model_metadata": {
            "statistical_deviation": {
                "entropy_normalised": 98.0,
                "max_abs_z": 2.0,
            },
            "sequence": {"support": 4},
            "probability_analysis": {"best_match_digit": 4},
            "hot_1000_continuation": {"status": "COLLECTING"},
            "cold_reversion": {"windows": {}},
        },
    }


def _adaptive():
    return {
        "candidate": 7,
        "verified_for_use": True,
        "supporting_models": ["frequency", "markov"],
    }


def test_precision_rejects_unvalidated_context():
    rows = [{
        "symbol": "R_100",
        "model": "frequency",
        "condition_family": "REGIME",
        "condition_value": "RANDOM",
        "discovery": {"resolved": 400, "lower_95_pct": 12.5},
        "validation": {
            "resolved": 150,
            "lower_95_pct": 11.0,
            "average_break_even_pct": 11.2,
        },
        "validation_economic_edge": False,
    }]
    decision = select_precision_candidate(_result(), _adaptive(), rows=rows)
    assert decision["verified_for_use"] is False
    assert decision["candidate"] is None


def test_precision_accepts_validated_active_context_same_digit():
    rows = [{
        "symbol": "R_100",
        "model": "frequency",
        "condition_family": "REGIME",
        "condition_value": "RANDOM",
        "discovery": {"resolved": 400, "lower_95_pct": 12.5},
        "validation": {
            "resolved": 150,
            "lower_95_pct": 12.1,
            "average_break_even_pct": 11.2,
        },
        "validation_economic_edge": True,
    }]
    decision = select_precision_candidate(_result(), _adaptive(), rows=rows)
    assert decision["verified_for_use"] is True
    assert decision["candidate"] == 7
    assert decision["supporting_model"] == "frequency"
    assert decision["conservative_edge_pp"] == 0.9


def test_precision_rejects_validated_row_when_model_predicts_other_digit():
    rows = [{
        "symbol": "R_100",
        "model": "sequence",
        "condition_family": "REGIME",
        "condition_value": "RANDOM",
        "discovery": {"resolved": 400, "lower_95_pct": 12.5},
        "validation": {
            "resolved": 150,
            "lower_95_pct": 12.2,
            "average_break_even_pct": 11.2,
        },
        "validation_economic_edge": True,
    }]
    decision = select_precision_candidate(_result(), _adaptive(), rows=rows)
    assert decision["verified_for_use"] is False
    assert decision["candidate"] is None


def test_precision_rejects_without_adaptive_verification():
    adaptive = {
        "candidate": 7,
        "verified_for_use": False,
        "supporting_models": ["frequency", "markov"],
    }
    decision = select_precision_candidate(_result(), adaptive, rows=[])
    assert decision["verified_for_use"] is False
    assert decision["candidate"] is None
