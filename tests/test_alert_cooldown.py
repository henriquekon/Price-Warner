from datetime import datetime, timedelta

from engine.alert_rules import cooldown_allows_alert
from engine.cycle_rules import CycleSnapshot, evaluate_cycle, mark_delivered


def test_further_drop_can_notify_one_hour_after_previous_email():
    now = datetime(2026, 11, 1, 10)
    previous = mark_delivered(CycleSnapshot(first_price=150, last_price=90, confirmed_high=150,
                                            confirmed_at=now), 90, now)
    decision = evaluate_cycle(previous, [150, 150, 90], 81, 10, now + timedelta(hours=1))
    assert decision.should_send
    assert cooldown_allows_alert("additional_drop", previous.last_alert_at, now + timedelta(hours=1), 24)


def test_recovery_alert_respects_configured_cooldown():
    now = datetime(2026, 11, 1, 10)
    assert not cooldown_allows_alert("recovery", now, now + timedelta(hours=1), 24)
    assert cooldown_allows_alert("recovery", now, now + timedelta(hours=24), 24)
    assert cooldown_allows_alert("first_drop", now, now + timedelta(minutes=3), 24)
