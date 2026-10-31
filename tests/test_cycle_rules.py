from datetime import datetime, timedelta

from engine.cycle_rules import CycleSnapshot, evaluate_cycle, mark_delivered

NOW = datetime(2026, 10, 31, 12, 0, 0)


def step(state, history, current, threshold=20, moment=NOW):
    decision = evaluate_cycle(state, history, current, threshold, moment)
    return decision, decision.snapshot


def test_cold_start_does_not_claim_promotion():
    result, state = step(CycleSnapshot(), [], 1000)
    assert not result.should_send
    result, state = step(state, [1000], 1000)
    assert not result.should_send


def test_initial_low_followed_by_recovery_and_drop():
    state = CycleSnapshot()
    history = []
    for price in [1000, 1000, 1500, 1500]:
        result, state = step(state, history, price)
        history.append(price)
        assert not result.should_send
    result, state = step(state, history, 1200)
    assert result.should_send
    assert result.reference == 1500


def test_single_spike_does_not_create_false_recovery():
    state = CycleSnapshot()
    history = []
    for price in [1000, 1000, 15000, 1000]:
        result, state = step(state, history, price)
        history.append(price)
    assert not result.should_send


def test_gradual_decline_triggers_at_threshold():
    state = CycleSnapshot()
    history = []
    alert = False
    for price in [1500, 1500] + list(range(1490, 1190, -10)):
        result, state = step(state, history[-30:], price, 15)
        alert |= result.should_send
        history.append(price)
    assert alert


def test_duplicate_and_further_drop():
    snapshot = mark_delivered(CycleSnapshot(first_price=1500, last_price=1200, confirmed_high=1500,
                                            confirmed_at=NOW), 1200, NOW)
    result, snapshot = step(snapshot, [1500, 1500, 1200], 1200, moment=NOW + timedelta(minutes=10))
    assert not result.should_send
    result, snapshot = step(snapshot, [1500, 1500, 1200, 1200], 1130, moment=NOW + timedelta(minutes=20))
    assert result.should_send


def test_recovery_then_new_cycle_raises_alert_again():
    snapshot = mark_delivered(CycleSnapshot(first_price=1000, last_price=1200, confirmed_high=1500,
                                            confirmed_at=NOW), 1200, NOW)
    prices = [1500, 1500, 1200]
    for index, price in enumerate([1500, 1500, 1200]):
        result, snapshot = step(snapshot, prices, price, moment=NOW + timedelta(minutes=30 * (index + 1)))
        prices.append(price)
    assert result.should_send


def test_stale_confirmed_peak_expires():
    state = CycleSnapshot(first_price=1500, last_price=1500, confirmed_high=1500,
                          confirmed_at=NOW - timedelta(days=31))
    result, _ = step(state, [1000, 1000, 1000], 1000)
    assert not result.should_send


def test_failed_delivery_does_not_advance_alert_state():
    result, state = step(CycleSnapshot(first_price=1500, last_price=1500, confirmed_high=1500,
                                       confirmed_at=NOW), [1500, 1500, 1500], 1200)
    assert result.should_send
    next_result, _ = step(state, [1500, 1500, 1500, 1200], 1200)
    assert next_result.should_send


def test_single_plausible_high_does_not_create_false_discount():
    state = CycleSnapshot()
    history = []
    for price in [1000, 1000, 1500]:
        result, state = step(state, history, price)
        history.append(price)
    result, _ = step(state, history, 1200, threshold=20)
    assert not result.should_send


def test_shared_product_has_isolated_monitoring_cycles():
    baseline = [1500, 1500, 1500]
    first, _ = step(CycleSnapshot(), baseline, 1200, threshold=20)
    second, _ = step(CycleSnapshot(), baseline, 1200, threshold=30)
    assert first.should_send
    assert not second.should_send
