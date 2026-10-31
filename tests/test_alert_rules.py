from engine.alert_rules import opportunity_reasons, should_notify


def test_gradual_decline_eventually_alerts():
    prices = [1500 - 10 * day for day in range(30)]
    assert opportunity_reasons(prices, 1200, 10)


def test_small_new_low_is_not_an_opportunity():
    assert opportunity_reasons([1500, 1495, 1490, 1485], 1484, 10) == []


def test_major_drop_alerts_immediately():
    assert opportunity_reasons([1500, 1500, 1500], 1030, 30)
    assert should_notify(1030, None, [])


def test_repeated_price_does_not_repeat_email():
    assert not should_notify(1030, 1030, [1030, 1030])


def test_further_drop_bypasses_cooldown():
    assert should_notify(950, 1030, [])


def test_recovery_and_new_promotion_alerts_again():
    assert should_notify(1020, 1030, [1200])
    assert not should_notify(1020, 1030, [1050])


def test_first_samples_do_not_trigger_false_alerts():
    assert opportunity_reasons([1500, 1400], 1200, 10) == []


def test_threshold_of_thirty_percent_not_met_by_twenty_percent_decline():
    assert not any('30%' in reason for reason in opportunity_reasons([1500, 1500, 1500], 1200, 30))


def test_reference_uses_recent_window_and_not_old_peak(tmp_path):
    from datetime import datetime, timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from data.models import Base, PriceHistory, Product, Store
    from engine.core import check_price_alerts

    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Store(id="kabum", name="Kabum"))
        item = Product(name="Laptop", store_id="kabum", url="https://example.com/laptop")
        db.add(item)
        db.flush()
        for price, days_ago in [(3000, 90), (1500, 20), (1450, 15), (1400, 10), (1350, 5)]:
            db.add(PriceHistory(product_id=item.id, price=price,
                                fetched_at=datetime.utcnow() - timedelta(days=days_ago)))
        db.commit()
        item.target_drop_percentage = 15
        assert check_price_alerts(db, item, 1300) == []
        assert check_price_alerts(db, item, 1100)


def test_thirty_percent_threshold_ignores_twenty_percent_new_low():
    assert opportunity_reasons([1500, 1500, 1500], 1200, 30) == []
