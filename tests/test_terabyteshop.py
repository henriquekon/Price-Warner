"""B1.6 TerabyteShop URL-only parser, browser routing, and image cache tests."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from data.models import User
from engine import image_cache
from engine.addon_cli import inspect_html
from engine.addons.registry import AddonValidationError, discover_addons, load_addon, validate_addon
from engine.addons.terabyteshop_parser import parse_terabyteshop_product
from engine.auth import current_user
from engine.browser_fetch import BrowserHTMLResponse
from engine.media import validate_product_image_url
from engine.scraper import AddonScraper
from main import app

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons/terabyteshop.json"
FIXTURES = ROOT / "tests/fixtures"
AVAILABLE = "https://www.terabyteshop.com.br/produto/31564/ssd-kingston-nv3-1tb-m2-nvme-2280-pcie-40-leitura-6000mbs-e-gravacao-4000mbs-snv3s1000g"
DISCOUNT = "https://www.terabyteshop.com.br/produto/27175/placa-de-video-biostar-amd-radeon-rx-580-8gb-gddr5-256-bit-va5815rq82"
REDIRECTED = "https://www.terabyteshop.com.br/produto/18574/ssd-wd-black-sn750se-500gb-m2-2280-leitura-3600mbs-e-gravacao-2000mbs-wds500g1b0e"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 26


def html(name):
    return (FIXTURES / f"terabyteshop_{name}.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("fixture,url,expected,original", [
    ("available", AVAILABLE, 1199.90, 2009.90),
    ("discount", DISCOUNT, 829.99, 1198.90),
])
def test_captured_product_cash_price_image_and_stock(fixture, url, expected, original):
    result = parse_terabyteshop_product(html(fixture), url)
    assert result["status"] == "ok" and result["ok"]
    assert result["availability"] == "in_stock"
    assert result["price"] == pytest.approx(expected)
    assert result["original_price"] == pytest.approx(original)
    assert result["price_kind"] == "pix_or_boleto"
    assert result["strategies_used"]["price"] == "terabyteshop_cash_verified"
    assert result["image_url"].startswith("https://img.terabyteshop.com.br/produto/m/")
    assert "R$" not in result["product_name"]


def test_category_redirect_never_uses_search_result_prices_as_product_price():
    result = parse_terabyteshop_product(html("category_redirect"), REDIRECTED)
    assert not result["ok"]
    assert result["status"] == "product_mismatch"
    assert result["price"] is None
    assert result["image_url"] is None


def test_real_product_schema_out_of_stock_preserves_history():
    document = html("available").replace('"InStock"', '"OutOfStock"').replace(
        "http://schema.org/InStock", "http://schema.org/OutOfStock"
    )
    result = parse_terabyteshop_product(document, AVAILABLE)
    assert result["ok"] and result["status"] == "out_of_stock"
    assert result["availability"] == "out_of_stock"
    assert result["price"] is None
    assert result["image_url"].startswith("https://img.terabyteshop.com.br/")


def test_inconsistent_or_missing_prices_fail_closed():
    document = html("available")
    wrong = document.replace('"price": "1199.90"', '"price": "1200.90"')
    if wrong == document:
        wrong = document.replace('"price":"1199.90"', '"price":"1200.90"')
    assert wrong != document
    result = parse_terabyteshop_product(wrong, AVAILABLE)
    assert result["status"] == "ambiguous_price"
    assert not result["ok"] and result["price"] is None
    no_price = document.replace("R$ 1.199,90", "").replace('"price": "1199.90"', '"price": null')
    if no_price != document:
        assert parse_terabyteshop_product(no_price, AVAILABLE)["price"] is None


def test_product_identity_and_host_checks():
    with pytest.raises(ValueError, match="Invalid TerabyteShop product URL"):
        parse_terabyteshop_product(html("available"), "https://evil.test/produto/31564/foo")
    assert parse_terabyteshop_product(html("available"), DISCOUNT)["status"] == "product_mismatch"
    assert parse_terabyteshop_product("<html><h1>Other site</h1></html>", AVAILABLE)["status"] == "invalid_page"
    assert parse_terabyteshop_product(html("available").replace('value="31564"', 'value="99999"'), AVAILABLE)["status"] == "product_mismatch"


def test_new_addon_uses_browser_and_disables_search():
    addon = load_addon(ADDON)
    assert addon["store"]["id"] == "terabyteshop"
    assert addon["request"]["transport"] == "playwright_firefox"
    assert "search" not in addon
    assert "terabyteshop" in discover_addons(ADDON.parent)
    assert load_addon(ADDON.parent / "pichau.json")["request"]["transport"] == "playwright_firefox"
    assert load_addon(ADDON.parent / "kabum.json")["request"].get("transport", "httpx") == "httpx"


def test_browser_transport_restricted_to_known_stores():
    addon = json.loads(ADDON.read_text(encoding="utf-8"))
    addon["store"]["base_url"] = "https://evil.test"
    with pytest.raises(AddonValidationError):
        validate_addon(addon)
    addon["store"]["id"] = "notterabyte"
    with pytest.raises(AddonValidationError):
        validate_addon(addon)


def test_cli_and_worker_parser_agree_and_browser_is_closed(monkeypatch):
    calls = []

    class FakeFetcher:
        def __init__(self, host, timeout):
            calls.append((host, timeout))
        def fetch(self, url, *, search=False):
            calls.append((url, search))
            return BrowserHTMLResponse(html("discount"))
        def close(self):
            calls.append("closed")

    monkeypatch.setattr("engine.browser_fetch.FirefoxHTMLFetcher", FakeFetcher)
    monkeypatch.setattr("engine.scraper._pace_browser_host", lambda *_: None)
    with AddonScraper(ADDON) as scraper:
        live = scraper.scrape(DISCOUNT)
        offline = scraper.scrape_html(html("discount"), DISCOUNT)
    cli = inspect_html(load_addon(ADDON), html("discount"), DISCOUNT)
    assert live["price"] == offline["price"] == cli["price"] == pytest.approx(829.99)
    assert live["image_url"] == offline["image_url"] == cli["image_url"]
    assert calls == [("www.terabyteshop.com.br", 30.0), (DISCOUNT, False), "closed"]


def test_store_image_proxy_and_cache_end_to_end(tmp_path, monkeypatch):
    addon = load_addon(ADDON)
    product = parse_terabyteshop_product(html("available"), AVAILABLE)
    image_url = product["image_url"]
    assert validate_product_image_url(image_url, addon) == image_url
    assert image_cache.image_proxy_url(image_url, "terabyteshop").startswith(
        "/media/image?store_id=terabyteshop&url="
    )
    assert image_cache.image_proxy_url("https://evil.test/a.jpg", "terabyteshop") is None
    assert image_cache.image_proxy_url("https://www.terabyteshop.com.br/", "terabyteshop") is None

    monkeypatch.setattr(image_cache, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(image_cache, "MIN_REQUEST_SPACING_SECONDS", 0)
    app.dependency_overrides[current_user] = lambda: User(id=1, email="test@example.invalid")
    try:
        with patch.object(image_cache, "_download_image", return_value=PNG) as download:
            with TestClient(app) as client:
                params = {"store_id": "terabyteshop", "url": image_url}
                first = client.get("/media/image", params=params)
                second = client.get("/media/image", params=params)
            assert first.status_code == second.status_code == 200
            assert first.headers["content-type"].startswith("image/png")
            assert first.content == PNG
            assert download.call_count == 1
    finally:
        app.dependency_overrides.clear()
