"""B1.7 Guerra Digital parsing, discovery, security, and media tests."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
import pytest

from data.models import User
from engine import image_cache
from engine.addon_cli import inspect_html
from engine.addons.guerra_digital_parser import parse_guerra_digital_product
from engine.addons.registry import AddonValidationError, discover_addons, load_addon, validate_addon
from engine.auth import current_user
from engine.media import validate_product_image_url
from engine.scraper import AddonScraper
from main import app

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons/guerra_digital.json"
FIXTURES = ROOT / "tests/fixtures"
AVAILABLE = "https://www.guerradigital.com.br/produtos/ssd-1-tb-kingston-nv3-m-2-2280-pcie-4-0-nvme-leitura-6000-mb-s-e-gravacao-4000-mb-s-snv3s-1000g/"
DISCOUNT = "https://www.guerradigital.com.br/produtos/ssd-netac-n530s-256gb-2-5-slc-3d-nand-sata-iii-n530s/"
SOLDOUT = "https://www.guerradigital.com.br/produtos/ssd-adata-su650-960-gb-sata-leitura-520mb-s-e-gravacao-450mb-s-asu650ss-960gt-r/"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 26


def html(name):
    return (FIXTURES / f"guerra_{name}.html").read_text(encoding="utf-8")


def test_available_product_price_stock_and_image():
    data = parse_guerra_digital_product(html("available"), AVAILABLE)
    assert data["ok"] and data["status"] == "ok"
    assert data["price"] == pytest.approx(1161.00)
    assert data["availability"] == "in_stock"
    assert data["price_kind"] == "pix_or_boleto"
    assert data["original_price"] is None
    assert data["strategies_used"]["price"] == "guerra_pix_visible"
    assert data["product_name"].startswith("SSD 1 TB Kingston NV3")
    assert data["image_url"].startswith(
        "https://acdn-us.mitiendanube.com/stores/002/025/067/products/"
    )
    assert data["image_url"].endswith(".webp")


@pytest.mark.parametrize("fixture,url,old_price", [
    ("discount_soldout", DISCOUNT, 210.00),
    ("soldout", SOLDOUT, None),
])
def test_out_of_stock_preserves_history_and_original_price(fixture, url, old_price):
    data = parse_guerra_digital_product(html(fixture), url)
    assert data["ok"] and data["status"] == "out_of_stock"
    assert data["availability"] == "out_of_stock"
    assert data["price"] is None
    assert data["original_price"] == old_price
    assert data["image_url"].startswith("https://acdn-us.mitiendanube.com/")


def test_discount_when_product_returns_to_stock():
    soup = BeautifulSoup(html("discount_soldout"), "html.parser")
    node = soup.select_one("#single-product")
    variants = json.loads(node["data-variants"])
    variants[0]["available"] = True
    variants[0]["stock"] = 2
    node["data-variants"] = json.dumps(variants)
    buy = soup.select_one('[data-store="product-buy-button"]')
    del buy["disabled"]
    buy["class"] = [x for x in buy["class"] if x != "nostock"]
    data = parse_guerra_digital_product(str(soup), DISCOUNT)
    assert data["status"] == "ok"
    assert data["price"] == pytest.approx(150.50)
    assert data["original_price"] == pytest.approx(210.00)
    assert data["price"] != 148.75
    assert data["price"] != 175.00


def test_canonical_and_product_form_mismatches_are_rejected():
    assert parse_guerra_digital_product(html("available"), DISCOUNT)["status"] == "product_mismatch"
    with pytest.raises(ValueError, match="Invalid Guerra Digital"):
        parse_guerra_digital_product(html("available"), "https://evil.example/produtos/ssd/")
    assert parse_guerra_digital_product(html("category"), AVAILABLE)["status"] == "invalid_page"
    changed = html("available").replace("product-form-251746182", "product-form-9999")
    assert parse_guerra_digital_product(changed, AVAILABLE)["status"] == "product_mismatch"
    changed = html("available").replace('rel="canonical"', 'rel="alternate"')
    assert parse_guerra_digital_product(changed, AVAILABLE)["status"] == "invalid_page"


def test_inconsistent_prices_are_rejected_without_false_alerts():
    data = parse_guerra_digital_product(
        html("available").replace('data-product-price="116100"', 'data-product-price="150000"'),
        AVAILABLE,
    )
    assert data["status"] == "ambiguous_price"
    assert not data["ok"] and data["price"] is None
    data = parse_guerra_digital_product(html("available").replace('id="price_display"', 'id="unknown"'), AVAILABLE)
    assert data["status"] == "price_unavailable"
    assert data["price"] is None


def test_stock_and_purchase_disagreement_does_not_report_availability():
    changed = html("available").replace('value="Comprar"', 'value="Esgotado"')
    changed = changed.replace('data-store="product-buy-button"', 'data-store="product-buy-button" disabled=""')
    result = parse_guerra_digital_product(changed, AVAILABLE)
    assert not result["ok"] and result["status"] == "availability_unknown"


def test_image_host_is_strictly_allowlisted():
    addon = load_addon(ADDON)
    image = parse_guerra_digital_product(html("available"), AVAILABLE)["image_url"]
    assert validate_product_image_url(image, addon) == image
    assert validate_product_image_url("https://not-mitiendanube.example/image.png", addon) is None
    document = html("available").replace("acdn-us.mitiendanube.com", "attacker.example")
    assert parse_guerra_digital_product(document, AVAILABLE)["image_url"] is None


def test_registry_and_httpx_transport():
    addon = load_addon(ADDON)
    assert addon["store"]["id"] == "guerra_digital"
    assert addon["request"].get("transport", "httpx") == "httpx"
    assert "guerra_digital" in discover_addons(ADDON.parent)
    assert addon["search"]["url_template"] == "https://www.guerradigital.com.br/search/?q={query}"
    evil = json.loads(ADDON.read_text(encoding="utf-8"))
    evil["store"]["base_url"] = "https://unrelated.example"
    with pytest.raises(AddonValidationError):
        validate_addon(evil)
    evil["store"]["base_url"] = "https://www.guerradigital.com.br"
    evil["store"]["id"] = "unrelated"
    with pytest.raises(AddonValidationError):
        validate_addon(evil)


def test_cli_and_worker_parse_identically():
    addon = load_addon(ADDON)
    with AddonScraper(ADDON) as scraper:
        result = scraper.scrape_html(html("available"), AVAILABLE)
    cli = inspect_html(addon, html("available"), AVAILABLE)
    assert cli["price"] == result["price"] == 1161.0
    assert cli["image_url"] == result["image_url"]
    assert cli["availability"] == result["availability"] == "in_stock"


def test_discovery_card_prices_images_and_stock():
    with AddonScraper(ADDON) as scraper:
        cards = scraper._extract_css_search_cards(
            BeautifulSoup(html("category"), "html.parser"),
            scraper.addon["search"]["strategies"][0],
        )
    assert len(cards) == 12
    kingston = next(x for x in cards if "Kingston NV3" in x["name"])
    assert kingston["price"] == pytest.approx(1161.00)
    assert kingston["store_id"] == "guerra_digital"
    assert kingston["url"].startswith(AVAILABLE)
    assert kingston["image_url"].startswith("https://acdn-us.mitiendanube.com/")
    assert "empty-placeholder" not in kingston["image_url"]
    assert all(x["image_url"] and x["image_url"].startswith("https://") for x in cards)


def test_discovery_out_of_stock_never_uses_hidden_esgotado_labels():
    soup = BeautifulSoup(html("category"), "html.parser")
    cards = soup.select(".js-item-product")
    hidden = soup.new_tag("div")
    hidden["class"] = ["js-stock-label"]
    hidden["style"] = "display:none"
    hidden.string = "Esgotado"
    cards[1].append(hidden)
    for card in cards:
        node = card.select_one("[data-variants]")
        if not node:
            continue
        variants = json.loads(node["data-variants"])
        variants[0]["available"] = False
        variants[0]["stock"] = 0
        node["data-variants"] = json.dumps(variants)
        break
    with AddonScraper(ADDON) as scraper:
        found = scraper._extract_css_search_cards(soup, scraper.addon["search"]["strategies"][0])
    assert found[0]["price"] is None
    assert found[1]["price"] == pytest.approx(1161.00)


def test_discovery_search_one_page_with_mock_response(monkeypatch):
    with AddonScraper(ADDON) as scraper:
        requested = []
        def fake_request(url, **kwargs):
            requested.append(url)
            return SimpleNamespace(text=html("category"))
        monkeypatch.setattr(scraper, "_make_request", fake_request)
        result = scraper.search_external_page("kingston nv3", page=1, page_size=20)
        assert len(result["items"]) == 12
        assert not result["has_next"]
        assert requested == ["https://www.guerradigital.com.br/search/?q=kingston%20nv3"]
        with pytest.raises(ValueError, match="pagination"):
            scraper.search_external_page("ssd", page=2)


def test_image_proxy_and_cache_with_mocked_cdn(tmp_path, monkeypatch):
    product = parse_guerra_digital_product(html("available"), AVAILABLE)
    url = product["image_url"]
    proxy = image_cache.image_proxy_url(url, "guerra_digital")
    assert proxy.startswith("/media/image?store_id=guerra_digital&url=")
    assert image_cache.image_proxy_url("https://evil.example/i.png", "guerra_digital") is None

    monkeypatch.setattr(image_cache, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(image_cache, "MIN_REQUEST_SPACING_SECONDS", 0)
    app.dependency_overrides[current_user] = lambda: User(id=1, email="test@example.invalid")
    try:
        with patch.object(image_cache, "_download_image", return_value=PNG) as download:
            with TestClient(app) as client:
                params = {"store_id": "guerra_digital", "url": url}
                first = client.get("/media/image", params=params)
                second = client.get("/media/image", params=params)
            assert first.status_code == second.status_code == 200
            assert first.headers["content-type"].startswith("image/png")
            assert first.content == PNG
            assert download.call_count == 1
    finally:
        app.dependency_overrides.clear()
