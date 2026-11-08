from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from engine.addon_cli import inspect_html
from engine.addons.amazon_parser import parse_amazon_product
from engine.addons.registry import load_addon
from engine.scraper import AddonScraper

ADDON = Path(__file__).resolve().parents[1] / "addons" / "amazon_br.json"
FIXTURE = Path(__file__).parent / "fixtures" / "amazon_international_hardcover.html"
URL = "https://www.amazon.com.br/dp/0872203492"


def sample():
    return FIXTURE.read_text(encoding="utf-8")


def test_international_hardcover_uses_primary_offer_not_kindle_or_related_prices():
    result = parse_amazon_product(sample(), URL)
    assert result.status == "ok"
    assert result.price == "355.93"
    assert result.availability == "in_stock"
    assert result.price_source == "amazon_core_offer_price"
    assert result.offer_origin == "international"
    assert len(result.variants) == 2
    assert [(x["label"], x["asin"], x["selected"], x["display_price"])
            for x in result.variants] == [
        ("Kindle", "B00OZ4NMHU", False, None),
        ("Capa dura", "0872203492", True, None),
    ]


def test_offline_scraper_and_cli_share_correct_hardcover_details():
    with AddonScraper(str(ADDON)) as scraper:
        result = scraper.scrape_html(sample(), URL)
    assert result["ok"]
    assert result["price"] == pytest.approx(355.93)
    assert result["url"] == URL
    assert result["offer_origin"] == "international"
    assert next(x for x in result["variants"] if x["selected"])["asin"] == "0872203492"
    cli = inspect_html(load_addon(ADDON), sample(), URL)
    assert cli["price"] == pytest.approx(355.93)
    assert cli["offer_origin"] == "international"
    assert len(cli["variants"]) == 2


def test_same_hardcover_asin_can_switch_to_unknown_origin_and_different_price():
    html = sample().replace("355.93", "299.00").replace("355,93", "299,00")
    soup = BeautifulSoup(html, "html.parser")
    soup.select_one("#globalStoreBadgePopoverInsideBuybox_feature_div").decompose()
    result = parse_amazon_product(str(soup), URL)
    assert result.asin == "0872203492"
    assert result.price == "299.00"
    assert result.offer_origin == "unknown"
    assert next(x for x in result.variants if x["selected"])["asin"] == "0872203492"


def test_conflicting_core_offer_amounts_are_rejected():
    html = sample().replace('data-csa-c-price-to-pay="355.93"', 'data-csa-c-price-to-pay="999.00"')
    result = parse_amazon_product(html, URL)
    assert result.status == "ambiguous_price"
    assert result.price is None


def test_missing_active_offer_does_not_use_kindle_or_related_product_prices():
    soup = BeautifulSoup(sample(), "html.parser")
    soup.select_one("#corePriceDisplay_desktop_feature_div").decompose()
    result = parse_amazon_product(str(soup), URL)
    assert result.status == "price_unavailable"
    assert result.price is None


def test_core_offer_for_another_asin_is_not_used():
    html = sample().replace('data-csa-c-asin="0872203492"', 'data-csa-c-asin="B00OZ4NMHU"')
    result = parse_amazon_product(html, URL)
    assert result.status == "price_unavailable"
    assert result.price is None


def test_hidden_import_instructions_do_not_prove_active_international_offer():
    soup = BeautifulSoup(sample(), "html.parser")
    badge = soup.select_one("#globalStoreBadgePopoverInsideBuybox_feature_div")
    badge.clear()
    hidden = soup.new_tag("div", attrs={"class": "a-popover-preload"})
    hidden.string = "Os tributos de importação estão incluídos."
    badge.append(hidden)
    result = parse_amazon_product(str(soup), URL)
    assert result.offer_origin == "unknown"
