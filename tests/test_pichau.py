"""Pichau B1.5 Pix offer, stock, search, image, and pagination tests."""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

import httpx
import pytest

from engine.addon_cli import inspect_html
from engine.addons.pichau_parser import parse_brl_price, parse_pichau_product
from engine.addons.registry import discover_addons, load_addon
from engine.scraper import AddonScraper, _SEARCH_SNAPSHOTS

ADDON = Path(__file__).resolve().parents[1] / "addons" / "pichau.json"
URL = "https://www.pichau.com.br/ssd-teste-1tb"
IMAGE = "https://media.pichau.com.br/media/catalog/product/example.jpg"


def product_html(*, meta="R$ 1,199.99", visible="R$ 1,199.99", stock="instock", builder=False):
    button = '<button class="Mui-disabled button-builderProductPage">Esgotado <small>Produto Indisponível</small></button>' if builder else ""
    return f'''<html><head><link rel="canonical" href="{URL}">
      <meta name="product:price:amount" content="{meta}">
      <meta name="product:availability" content="{stock}">
      <meta property="og:image" content="{IMAGE}"></head>
      <body><h1>SSD Teste 1TB</h1>
      <div class="price_from">de R$ 2,235.28</div>
      <div class="price_vista">{visible}</div>
      <div class="price_total">R$ 1,411.75</div>{button}</body></html>'''


@pytest.mark.parametrize("text,expected", [
    ("R$ 1,199.99", 1199.99),
    ("R$ 7,058.81", 7058.81),
    ("R$ 1.199,99", 1199.99),
    ("R$ 1199,99", 1199.99),
    ("R$ 1199.99", 1199.99),
    ("R$ 5,549.99", 5549.99),
])
def test_price_formats(text, expected):
    assert parse_brl_price(text) == pytest.approx(expected)


def test_pichau_pix_price_not_previous_or_installments():
    result = parse_pichau_product(product_html(), URL)
    assert result["ok"] is True
    assert result["price"] == pytest.approx(1199.99)
    assert result["strategies_used"]["price"] == "pichau_pix_verified"
    assert result["availability"] == "in_stock"


def test_out_of_stock_keeps_null_price_even_when_metadata_has_price():
    result = parse_pichau_product(product_html(stock="outofstock"), URL)
    assert result["ok"] is True
    assert result["price"] is None
    assert result["availability"] == "out_of_stock"


def test_disabled_builder_button_overrides_misleading_stock_metadata():
    result = parse_pichau_product(product_html(builder=True), URL)
    assert result["ok"] is True
    assert result["status"] == "out_of_stock"
    assert result["price"] is None


def test_conflicting_pix_prices_fail_closed():
    result = parse_pichau_product(product_html(meta="R$ 1,199.99", visible="R$ 99.99"), URL)
    assert result["ok"] is False
    assert result["status"] == "ambiguous_price"
    assert result["price"] is None


def test_unknown_availability_fail_closed():
    result = parse_pichau_product(product_html(stock="unverified"), URL)
    assert result["ok"] is False
    assert result["status"] == "availability_unknown"


def test_mismatched_canonical_does_not_return_other_product_price():
    result = parse_pichau_product(product_html().replace("/ssd-teste-1tb", "/outro-produto"), URL)
    assert result["status"] == "product_mismatch"
    assert result["price"] is None


def test_custom_addon_and_cli_match():
    addon = load_addon(ADDON)
    with AddonScraper(ADDON) as scraper:
        result = scraper.scrape_html(product_html(), URL)
    cli_result = inspect_html(addon, product_html(), URL)
    assert result["price"] == cli_result["price"] == 1199.99
    assert result["image_url"] == cli_result["image_url"] == IMAGE
    assert "pichau" in discover_addons(ADDON.parent)


def search_page(index: int):
    start = (index - 1) * 36
    cards = []
    for n in range(start + 1, start + 37):
        cards.append(f'''<a data-cy="list-product" href="/ssd-{n}">
          <img src="{IMAGE}"/><h2>SSD {n}</h2>
          <div class="price_from">de R$ 7,058.81</div>
          <div class="price_vista">R$ 5,549.99</div>
          <div class="price_total">R$ 6,529.40</div></a>''')
    next_page = f'<a aria-label="Go to next page" href="/search?q=ssd&page={index + 1}">Next</a>' if index < 2 else ""
    return "<html>" + "".join(cards) + next_page + "</html>"


def test_search_pagination_36_items_per_store_page_and_images(monkeypatch):
    _SEARCH_SNAPSHOTS.clear()
    with AddonScraper(ADDON) as scraper:
        def fake_fetch(url, **kwargs):
            params = parse_qs(urlsplit(url).query)
            n = int(params.get("page", ["1"])[0])
            return httpx.Response(200, request=httpx.Request("GET", url), text=search_page(n))
        monkeypatch.setattr(scraper, "_make_request", fake_fetch)
        monkeypatch.setattr("engine.scraper.time.sleep", lambda _: None)
        first = scraper.search_external_page("ssd", 1, 50)
        second = scraper.search_external_page("ssd", 2, 50)
        assert len(first["items"]) == 50
        assert len(second["items"]) == 22
        assert first["items"][0]["name"] == "SSD 1"
        assert first["items"][-1]["name"] == "SSD 50"
        assert second["items"][0]["name"] == "SSD 51"
        assert first["items"][0]["price"] == pytest.approx(5549.99)
        assert first["items"][0]["image_url"] == IMAGE
        assert first["items"][0]["url"] == "https://www.pichau.com.br/ssd-1"
        assert not second["has_next"]
    _SEARCH_SNAPSHOTS.clear()


def test_search_excludes_out_of_stock_price():
    html = '''<html><a data-cy="list-product" href="/ssd-1"><h2>SSD 1</h2>
      <div class="price_vista">R$ 399.99</div><span>Esgotado</span><img src="https://media.pichau.com.br/a.jpg"></a></html>'''
    with AddonScraper(ADDON) as scraper:
        from bs4 import BeautifulSoup
        item = scraper._extract_css_search_cards(BeautifulSoup(html,"html.parser"), scraper.addon["search"]["strategies"][0])[0]
        assert item["price"] is None


def test_other_store_parsers_remain_supported():
    assert load_addon(ADDON.parent / "amazon_br.json")["parser"] == "amazon_br"
    assert load_addon(ADDON.parent / "kabum.json")["store"]["id"] == "kabum"
