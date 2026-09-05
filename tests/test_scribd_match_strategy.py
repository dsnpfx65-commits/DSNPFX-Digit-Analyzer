from backend.core.scribd_match_strategy import RULES, analyze_scribd_match, evaluate_snapshot


def neutral_deltas():
    return {digit: 0.0 for digit in range(10)}


def test_all_ten_rules_are_defined():
    assert set(RULES) == set(range(10))
    assert RULES[0].entry_cursor == 2
    assert RULES[1].entry_cursor == 3
    assert RULES[9].entry_cursor == 4


def test_match_one_requires_0_2_3_below_ten_and_cursor_three():
    percentages = {digit: 11.0 for digit in range(10)}
    for digit in (0, 2, 3):
        percentages[digit] = 9.0
    report = evaluate_snapshot(
        percentages=percentages,
        trend_delta_pp=neutral_deltas(),
        cursor_digit=3,
    )[1]
    assert report["status"] == "READY"


def test_match_one_rejects_wrong_cursor():
    percentages = {digit: 11.0 for digit in range(10)}
    for digit in (0, 2, 3):
        percentages[digit] = 9.0
    report = evaluate_snapshot(
        percentages=percentages,
        trend_delta_pp=neutral_deltas(),
        cursor_digit=2,
    )[1]
    assert report["status"] == "WAITING"
    assert report["cursor_gate"] is False


def test_match_zero_uses_at_least_three_below_ten():
    percentages = {digit: 11.0 for digit in range(10)}
    percentages.update({1: 9.0, 4: 9.0, 8: 9.0})
    report = evaluate_snapshot(
        percentages=percentages,
        trend_delta_pp=neutral_deltas(),
        cursor_digit=2,
    )[0]
    assert report["status"] == "READY"


def test_target_direction_blocks_non_neutral_target():
    percentages = {digit: 11.0 for digit in range(10)}
    for digit in (0, 2, 3):
        percentages[digit] = 9.0
    deltas = neutral_deltas()
    deltas[1] = 2.5
    report = evaluate_snapshot(
        percentages=percentages,
        trend_delta_pp=deltas,
        cursor_digit=3,
    )[1]
    assert report["target_neutral"] is False
    assert report["status"] == "WAITING"


def test_analyzer_collects_until_window_is_available():
    report = analyze_scribd_match([0, 1, 2] * 10)
    assert report["status"] == "COLLECTING"
    assert report["ready_targets"] == []
