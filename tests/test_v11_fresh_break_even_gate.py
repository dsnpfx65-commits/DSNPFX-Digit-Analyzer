from backend.core.v11_selective_demo_trader import (
    CURRENT_VERSION,
    MIN_VALIDATION_TO_TRADE,
    V11SelectiveDemoTrader,
)


def _selection(lower=12.5, avg_be=11.2):
    return {
        "strategy_version": CURRENT_VERSION,
        "symbol": "R_75",
        "model": "markov",
        "condition_family": "REGIME",
        "condition_value": "BALANCED",
        "prediction": 7,
        "source_epoch": 100,
        "source_quote": "123.45",
        "validation": {
            "resolved": MIN_VALIDATION_TO_TRADE,
            "lower_95_pct": lower,
            "average_break_even_pct": avg_be,
        },
    }


def _proposal(be=11.8, digit=7, contract_type="DIGITMATCH"):
    return {
        "status": "LIVE",
        "symbol": "R_75",
        "digit": digit,
        "contract_type": contract_type,
        "break_even_probability_pct": be,
        "ask_price": 1.0,
        "payout": 8.5,
        "proposal_id": "proposal-1",
    }


def test_rejects_fresh_break_even_above_validation_lower(tmp_path):
    trader = V11SelectiveDemoTrader(str(tmp_path / "v11.db"))
    assert trader.commit_candidate(_selection(lower=12.0), _proposal(be=12.1)) is False


def test_accepts_only_when_validation_lower_clears_fresh_break_even(tmp_path):
    trader = V11SelectiveDemoTrader(str(tmp_path / "v11.db"))
    assert trader.commit_candidate(_selection(lower=12.5), _proposal(be=11.8)) is True
    row = trader.connection.execute("SELECT * FROM demo_trades").fetchone()
    assert row["break_even_probability_pct"] == 11.8
    assert row["prediction"] == 7


def test_rejects_wrong_digit_or_contract(tmp_path):
    trader = V11SelectiveDemoTrader(str(tmp_path / "v11.db"))
    assert trader.commit_candidate(_selection(), _proposal(digit=6)) is False
    assert trader.commit_candidate(_selection(), _proposal(contract_type="DIGITDIFF")) is False
