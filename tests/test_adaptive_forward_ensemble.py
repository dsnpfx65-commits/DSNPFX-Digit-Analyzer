from backend.core.adaptive_forward_ensemble import AdaptiveForwardEnsemble


def _seed_model(engine, *, symbol, model, prediction, wins, losses, break_even=11.2):
    epoch = 1
    for index in range(wins + losses):
        assert engine.create_prediction(
            symbol=symbol,
            model=model,
            prediction=prediction,
            source_epoch=epoch,
            source_quote="100.00",
            break_even_probability_pct=break_even,
        )
        actual = prediction if index < wins else (prediction + 1) % 10
        resolved = engine.resolve(
            symbol,
            actual,
            tick_epoch=epoch + 1,
            tick_quote="100.01",
        )
        assert len(resolved) == 1
        epoch += 2


def test_model_must_beat_live_break_even_not_just_ten_percent(tmp_path):
    engine = AdaptiveForwardEnsemble(str(tmp_path / "adaptive.db"))
    try:
        _seed_model(
            engine,
            symbol="R_100",
            model="frequency",
            prediction=7,
            wins=15,
            losses=85,
            break_even=14.0,
        )
        stats = engine.statistics("R_100", "frequency")
        assert stats["accuracy_pct"] == 15.0
        assert stats["statistical_eligible"] is False or stats["tradable_eligible"] is False
        assert stats["tradable_eligible"] is False
        assert stats["raw_evidence_weight"] == 0.0
    finally:
        engine.close()


def test_one_profitable_model_cannot_publish_prediction(tmp_path):
    engine = AdaptiveForwardEnsemble(str(tmp_path / "adaptive.db"))
    try:
        _seed_model(
            engine,
            symbol="1HZ100V",
            model="frequency",
            prediction=6,
            wins=30,
            losses=70,
        )
        decision = engine.choose(
            "1HZ100V",
            {
                "frequency": 6,
                "markov": 2,
                "sequence": 4,
                "probability_best": 3,
                "hot_1000": 1,
                "cold_1000": 8,
            },
        )
        assert decision["verified_for_use"] is False
        assert decision["candidate"] is None
        assert decision["support_count"] == 1
    finally:
        engine.close()


def test_two_profitable_models_must_agree_for_single_prediction(tmp_path):
    engine = AdaptiveForwardEnsemble(str(tmp_path / "adaptive.db"))
    try:
        _seed_model(
            engine,
            symbol="1HZ75V",
            model="frequency",
            prediction=8,
            wins=30,
            losses=70,
        )
        _seed_model(
            engine,
            symbol="1HZ75V",
            model="markov",
            prediction=8,
            wins=28,
            losses=72,
        )

        decision = engine.choose(
            "1HZ75V",
            {
                "frequency": 8,
                "markov": 8,
                "sequence": 1,
                "probability_best": 3,
                "hot_1000": 5,
                "cold_1000": 6,
            },
        )

        assert decision["verified_for_use"] is True
        assert decision["candidate"] == 8
        assert decision["support_count"] == 2
        assert set(decision["supporting_models"]) == {"frequency", "markov"}
        assert decision["weight_share_pct"] == 100.0
    finally:
        engine.close()


def test_profitable_models_that_disagree_do_not_publish(tmp_path):
    engine = AdaptiveForwardEnsemble(str(tmp_path / "adaptive.db"))
    try:
        _seed_model(
            engine,
            symbol="R_75",
            model="frequency",
            prediction=2,
            wins=30,
            losses=70,
        )
        _seed_model(
            engine,
            symbol="R_75",
            model="markov",
            prediction=5,
            wins=30,
            losses=70,
        )

        decision = engine.choose(
            "R_75",
            {
                "frequency": 2,
                "markov": 5,
                "sequence": 1,
                "probability_best": 3,
                "hot_1000": 7,
                "cold_1000": 9,
            },
        )

        assert decision["verified_for_use"] is False
        assert decision["candidate"] is None
        assert decision["support_count"] == 1
    finally:
        engine.close()
