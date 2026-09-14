import asyncio

from backend.core.v12_demo_auto_executor import (
    DemoExecutionConfig,
    DemoExecutionLedger,
    V12DemoAutoExecutor,
)


class FakeDemoClient:
    def __init__(self, *, status="won", profit=2.1):
        self.status = status
        self.profit = profit
        self.buys = []
        self.closed = False

    async def buy_proposal(self, proposal_id, max_price):
        self.buys.append((proposal_id, max_price))
        return {"contract_id": "demo-contract-1"}

    async def wait_for_settlement(self, contract_id):
        return {
            "contract_id": contract_id,
            "status": self.status,
            "is_sold": 1,
            "profit": self.profit,
        }

    async def close(self):
        self.closed = True


def config(**overrides):
    values = dict(
        enabled=True,
        account_id="DEMO-ONLY",
        auth_token="test-token",
        app_id="test-app",
        stake=0.35,
        max_consecutive_losses=3,
        session_stop_loss_units=3.0,
        session_take_profit_units=5.0,
        request_timeout_seconds=1.0,
    )
    values.update(overrides)
    return DemoExecutionConfig(**values)


def result(prediction=7, lower=12.5):
    return {
        "symbol": "1HZ100V",
        "prediction_source": "V12_PRECISION_CONDITIONAL_GATE",
        "prediction": prediction,
        "precision_decision": {
            "verified_for_use": True,
            "candidate": prediction,
            "validation_lower_95_pct": lower,
        },
    }


def proposal(digit=7, break_even=11.2):
    return {
        "status": "LIVE",
        "symbol": "1HZ100V",
        "digit": digit,
        "contract_type": "DIGITMATCH",
        "proposal_id": "proposal-123",
        "break_even_probability_pct": break_even,
        "ask_price": 0.35,
        "payout": 3.125,
        "stake": 0.35,
    }


def make_executor(tmp_path, *, cfg=None, client=None):
    ledger = DemoExecutionLedger(str(tmp_path / "execution.db"))
    return V12DemoAutoExecutor(
        config=cfg or config(),
        ledger=ledger,
        client=client or FakeDemoClient(),
    )


def test_disabled_by_default_blocks_execution(tmp_path):
    executor = make_executor(tmp_path, cfg=config(enabled=False))
    ok, reason = executor.validate(
        result(), {"epoch": 100}, {"epoch": 100}, proposal()
    )
    assert ok is False
    assert reason == "AUTO_DEMO_DISABLED"


def test_fresh_break_even_must_be_cleared(tmp_path):
    executor = make_executor(tmp_path)
    ok, reason = executor.validate(
        result(lower=11.1), {"epoch": 100}, {"epoch": 100}, proposal(break_even=11.2)
    )
    assert ok is False
    assert reason == "FRESH_BREAK_EVEN_NOT_CLEARED"


def test_newer_tick_blocks_stale_buy(tmp_path):
    executor = make_executor(tmp_path)
    ok, reason = executor.validate(
        result(), {"epoch": 100}, {"epoch": 101}, proposal()
    )
    assert ok is False
    assert reason == "STALE_SOURCE_TICK"


def test_wrong_contract_or_digit_is_rejected(tmp_path):
    executor = make_executor(tmp_path)
    wrong_contract = proposal()
    wrong_contract["contract_type"] = "DIGITDIFF"
    assert executor.validate(result(), {"epoch": 100}, {"epoch": 100}, wrong_contract)[1] == "WRONG_CONTRACT_TYPE"
    assert executor.validate(result(), {"epoch": 100}, {"epoch": 100}, proposal(digit=4))[1] == "PROPOSAL_DIGIT_MISMATCH"


def test_verified_v12_demo_trade_buys_and_settles(tmp_path):
    fake = FakeDemoClient(status="won", profit=2.1)
    executor = make_executor(tmp_path, client=fake)
    outcome = asyncio.run(executor.execute(
        result(), {"epoch": 100, "quote": "123.47"}, {"epoch": 100, "quote": "123.47"}, proposal()
    ))
    assert outcome["executed"] is True
    assert outcome["result"] == "WIN"
    assert fake.buys == [("proposal-123", 0.35)]
    metrics = executor.ledger.session_metrics()
    assert metrics["resolved"] == 1
    assert metrics["pnl"] == 2.1


def test_three_consecutive_losses_trip_kill_switch(tmp_path):
    executor = make_executor(tmp_path)
    for index in range(3):
        trade_id = executor.ledger.record_buying(
            symbol="1HZ100V",
            prediction=7,
            source_epoch=index + 1,
            proposal_id=f"p-{index}",
            proposal_break_even_pct=11.2,
            validation_lower_95_pct=12.5,
            stake=0.35,
        )
        executor.ledger.settle(trade_id, profit=-0.35, result="LOSS")
    ok, reason = executor.validate(
        result(), {"epoch": 100}, {"epoch": 100}, proposal()
    )
    assert ok is False
    assert reason == "MAX_CONSECUTIVE_LOSSES"
