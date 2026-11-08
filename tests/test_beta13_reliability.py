"""B1.3 parser compatibility and worker diagnostics regression tests."""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from data.models import Base, Monitoring, PriceHistory, Product, Store, User, WorkerState
from engine import core
from engine.addons.amazon_parser import parse_amazon_product
from engine.health_api import system_health, worker_health

ASIN = "0872203492"
URL = f"https://www.amazon.com.br/dp/{ASIN}"
INTERNATIONAL = Path(__file__).parent / "fixtures" / "amazon_international_hardcover.html"


def wrap(content: str) -> str:
    return f'<html><span id="productTitle">Hardcover Book</span>{content}</html>'


def legacy_price(amount: str) -> str:
    return f'<div id="buybox"><div class="a-accordion-active"><span class="a-price"><span class="a-offscreen">R$ {amount}</span></span></div></div>'


def new_price(amount: str) -> str:
    return f'<div id="corePriceDisplay_desktop_feature_div" data-csa-c-asin="{ASIN}"><span class="apex-core-price-identifier" data-csa-c-price-to-pay="{amount}"></span></div>'


def test_classic_amazon_layout_remains_supported():
    result = parse_amazon_product(wrap(legacy_price("299,00")), URL)
    assert result.status == "ok"
    assert result.price == "299.00"
    assert result.price_source == "legacy_one_time_purchase"


def test_new_amazon_layout_remains_supported():
    result = parse_amazon_product(INTERNATIONAL.read_text(), URL)
    assert result.status == "ok"
    assert result.price == "355.93"
    assert result.price_source == "amazon_core_offer_price"
    assert result.offer_origin == "international"


def test_both_layouts_agree_on_price():
    result = parse_amazon_product(wrap(legacy_price("355,93") + new_price("355.93")), URL)
    assert result.status == "ok"
    assert result.price == "355.93"


def test_disagreeing_layouts_fail_closed_instead_of_alerting():
    result = parse_amazon_product(wrap(legacy_price("199,90") + new_price("355.93")), URL)
    assert result.status == "ambiguous_price"
    assert result.price is None


def test_narrow_fallback_price_from_main_buy_box():
    result = parse_amazon_product(wrap('<span id="priceblock_ourprice">R$ 149,90</span>'), URL)
    assert result.status == "ok"
    assert result.price == "149.90"
    assert result.price_source == "scoped_primary_price"


def test_fallback_does_not_consume_alternate_kindle_or_hidden_prices():
    html = '''<span id="productTitle">Book</span>
      <div id="inline-twister-row-media_format">
        <span id="priceblock_ourprice">R$ 19,90</span>
      </div><span style="display:none" id="price_inside_buybox">R$ 17,90</span>'''
    result = parse_amazon_product(wrap(html), URL)
    assert result.status == "price_unavailable"


def memory_database():
    connection = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(connection)
    return connection


def test_health_is_scoped_to_account_and_detects_stale_worker():
    engine = memory_database()
    with Session(engine) as db:
        db.add_all([User(id=1, email="first@example.test"), User(id=2, email="second@example.test"),
                    Store(id="amazon_br", name="Amazon Brasil")])
        db.flush()
        db.add_all([
            Product(id=1, name="One", url=URL, store_id="amazon_br", last_checked=datetime.utcnow(), last_error="captcha_required"),
            Product(id=2, name="Other", url="https://www.amazon.com.br/dp/B012345678", store_id="amazon_br", last_checked=datetime.utcnow(), last_error="private error"),
        ])
        db.flush()
        db.add_all([Monitoring(user_id=1, product_id=1), Monitoring(user_id=2, product_id=2),
                    WorkerState(id=1, state="idle", last_started_at=datetime.utcnow() - timedelta(hours=1),
                                last_finished_at=datetime.utcnow() - timedelta(hours=1), last_failed=0)])
        db.commit()
        report = system_health(db=db, user=db.get(User, 1))
        assert report["summary"]["monitored"] == 1
        assert report["summary"]["errors"] == 1
        assert report["worker"]["status"] == "stale"
        assert report["worker"]["last_cycle"] is None
        assert len(report["recent_errors"]) == 1
        assert report["recent_errors"][0]["error"] == "captcha_required"
        assert report["stores"][0]["monitored"] == 1
        assert "private error" not in repr(report)
    engine.dispose()


def test_worker_updates_persistent_cycle_heartbeat(monkeypatch):
    engine = memory_database()
    with Session(engine) as db:
        db.add_all([User(id=1, email="user@example.test"), Store(id="amazon_br", name="Amazon Brasil")])
        db.flush()
        db.add(Product(id=7, name="Book", url=URL, store_id="amazon_br"))
        db.flush()
        db.add(Monitoring(user_id=1, product_id=7, interval=60))
        db.commit()
    monkeypatch.setattr(core, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(core, "check_product", lambda _id, _notifier: "out_of_stock")
    assert core.run_due_checks(Mock()) == {"ok": 0, "out_of_stock": 1, "failed": 0, "skipped": 0}
    with Session(engine) as db:
        state = db.get(WorkerState, 1)
        assert state.state == "idle"
        assert state.last_checked == 1
        assert state.last_failed == 0
        assert state.last_out_of_stock == 1
        assert worker_health(db, datetime.utcnow())["status"] == "healthy"
    engine.dispose()


def test_price_unavailable_keeps_history_and_records_diagnostic(monkeypatch, caplog):
    engine = memory_database()
    with Session(engine) as db:
        db.add_all([User(id=1, email="user@example.test"), Store(id="amazon_br", name="Amazon Brasil")])
        db.flush()
        db.add(Product(id=10, name="Book", url=URL, store_id="amazon_br"))
        db.flush()
        db.add(Monitoring(user_id=1, product_id=10, interval=60))
        db.add(PriceHistory(product_id=10, price=355.93, availability="in_stock"))
        db.commit()
    monkeypatch.setattr(core, "SessionLocal", lambda: Session(engine))
    monkeypatch.setattr(core.AddonScraper, "scrape", lambda *_: {
        "ok": False, "status": "ambiguous_price", "reason": "Conflicting one-time purchase prices",
        "price": None, "availability": "unknown", "image_url": None,
    })
    with caplog.at_level("WARNING"):
        outcome = core.check_product(10, Mock())
    assert outcome == "failed"
    assert "status=ambiguous_price" in caplog.text
    with Session(engine) as db:
        assert db.query(PriceHistory).filter(PriceHistory.product_id == 10).count() == 1
        assert "ambiguous_price" in db.get(Product, 10).last_error
    engine.dispose()
