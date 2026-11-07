"""Amazon discovery, product imagery and availability using synthetic public HTML."""

from pathlib import Path
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from bs4 import BeautifulSoup
import httpx
import pytest

from data.models import Base, Monitoring, PriceHistory, Product, Store, User
from engine.addon_cli import inspect_html
from engine.addons.registry import load_addon
from engine.addons.amazon_parser import parse_amazon_product
from engine.dashboard_api import dashboard
from engine.image_cache import image_proxy_url
from engine.scraper import AddonScraper, _SEARCH_SNAPSHOTS
from engine import core

ADDON = Path(__file__).resolve().parents[1] / "addons" / "amazon_br.json"
URL = "https://www.amazon.com.br/dp/B0CQMT33WX"
IMAGE = "https://m.media-amazon.com/images/I/AAAAAA.jpg"


def out_of_stock_html():
    return f'''<html><title>Fire TV Stick HD</title><div id="productTitle">Fire TV Stick HD</div>
    <div id="availability">Não disponível. Não temos previsão de quando este produto estará disponível novamente.</div>
    <div id="outOfStock"><span>Não disponível</span></div>
    <img id="landingImage" src="{IMAGE}"></html>'''


def search_html(start: int, count: int, next_page: bool, overlap: int = 0):
    cards = []
    for index in range(start-overlap, start+count):
        asin = f"B{index:09d}"
        cards.append(f'''<div data-component-type="s-search-result" data-asin="{asin}">
          <h2><span>SSD Product {index}</span></h2>
          <span class="a-price"><span class="a-offscreen">R$ 1.299,90</span></span>
          <img class="s-image" src="https://m.media-amazon.com/images/I/{index}.jpg"></div>''')
    link = '<a class="s-pagination-next" href="/s?k=ssd&page=2">Next</a>' if next_page else ''
    return '<html><title>Amazon search</title>' + ''.join(cards) + link + '</html>'


def test_amazon_unavailable_is_valid_check_with_no_price_and_local_image():
    product = parse_amazon_product(out_of_stock_html(), URL)
    assert product.status == "out_of_stock"
    assert product.price is None
    assert product.availability == "out_of_stock"
    assert product.image_url == IMAGE
    with AddonScraper(str(ADDON)) as scraper:
        result = scraper.scrape_html(out_of_stock_html(), URL)
    assert result["ok"] is True
    assert result["status"] == "out_of_stock"
    assert result["price"] is None
    assert result["image_url"] == IMAGE
    assert image_proxy_url(IMAGE, "amazon_br").startswith("/media/image?")
    assert inspect_html(load_addon(ADDON), out_of_stock_html(), URL)["ok"] is True


def test_unknown_price_still_error_and_foreign_image_refused():
    with AddonScraper(str(ADDON)) as scraper:
        unknown = scraper.scrape_html('<div id="productTitle">Item</div>', URL)
        foreign = scraper.scrape_html('<div id="productTitle">Item</div>'
            '<div id="availability">Não disponível</div>'
            '<img id="landingImage" src="https://example.com/secret.jpg">', URL)
    assert unknown["ok"] is False
    assert unknown["status"] == "price_unavailable"
    assert foreign["ok"] is True
    assert foreign["image_url"] is None


def test_search_extracts_canonical_asins_prices_and_images():
    soup = BeautifulSoup(search_html(1, 4, False), "html.parser")
    with AddonScraper(str(ADDON)) as scraper:
        items = scraper._extract_css_search_cards(soup, scraper.addon["search"]["strategies"][0])
    assert len(items) == 4
    assert items[0] == {
        "name": "SSD Product 1", "url": "https://www.amazon.com.br/dp/B000000001",
        "price": 1299.90, "image_url": "https://m.media-amazon.com/images/I/1.jpg",
        "store_id": "amazon_br",
    }


def test_pagination_reuses_snapshot_and_never_skips_or_repeats_cards(monkeypatch):
    _SEARCH_SNAPSHOTS.clear()
    pages = {1: search_html(1, 60, True), 2: search_html(61, 25, False, overlap=5)}
    calls = []
    with AddonScraper(str(ADDON)) as scraper:
        def get_page(url, **kwargs):
            from urllib.parse import parse_qs, urlsplit
            number = int(parse_qs(urlsplit(url).query)["page"][0])
            calls.append(number)
            return httpx.Response(200, text=pages[number], request=httpx.Request("GET", url))
        monkeypatch.setattr(scraper, "_make_request", get_page)
        monkeypatch.setattr("engine.scraper.time.sleep", lambda _: None)
        results = [scraper.search_external_page("ssd nvme", page=p, page_size=20)
                   for p in (1, 2, 3, 4, 5)]
    assert calls == [1, 2]
    assert list(map(len, (r["items"] for r in results))) == [20, 20, 20, 20, 5]
    urls = [item["url"] for result in results for item in result["items"]]
    assert len(set(urls)) == len(urls) == 85
    assert results[-1]["has_next"] is False
    assert results[-1]["total"] == 85
    _SEARCH_SNAPSHOTS.clear()


def test_search_captcha_is_not_silently_reported_as_empty_results(monkeypatch):
    _SEARCH_SNAPSHOTS.clear()
    with AddonScraper(str(ADDON)) as scraper:
        def blocked(url, **kwargs):
            return httpx.Response(200, text='<html><title>Robot Check</title>'
                '<form action="/errors/validateCaptcha"></form></html>',
                request=httpx.Request("GET", url))
        monkeypatch.setattr(scraper, "_make_request", blocked)
        with pytest.raises(ValueError, match="manual verification"):
            scraper.search_external_page("ssd nvme")
    _SEARCH_SNAPSHOTS.clear()


def test_out_of_stock_price_history_keeps_last_known_price_in_dashboard(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(id=1, email="amazon-test@example.test"), Store(id="amazon_br", name="Amazon Brasil")])
        db.flush()
        product = Product(name="Fire TV", url=URL, store_id="amazon_br", interval=60)
        db.add(product)
        db.flush()
        db.add(Monitoring(user_id=1, product_id=product.id, interval=60))
        db.add(PriceHistory(product_id=product.id, price=79.90, availability="in_stock"))
        db.flush()
        old_id = product.id
        db.commit()
        monkeypatch.setattr(core, "SessionLocal", lambda: Session(engine))
        monkeypatch.setattr(core.AddonScraper, "scrape", lambda _self, _url: {
            "ok": True, "status": "out_of_stock", "price": None, "availability": "out_of_stock",
            "image_url": IMAGE, "strategies_used": {"price": None},
        })
        core.check_product(old_id, Mock())
        rows = db.query(PriceHistory).filter(PriceHistory.product_id == old_id).all()
        assert len(rows) == 2
        assert rows[-1].price is None
        assert rows[-1].availability == "out_of_stock"
        page = dashboard(period="7d", page=1, page_size=20, q="", store_id="all", status="all",
                         db=db, user=db.get(User, 1))
        assert page["products"][0]["price"] == 79.90
        assert page["products"][0]["availability"] == "out_of_stock"
        assert db.get(Product, old_id).last_error is None
    engine.dispose()
