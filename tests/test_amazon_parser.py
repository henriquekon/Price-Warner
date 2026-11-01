from pathlib import Path

import pytest

from engine.addons.amazon_parser import normalize_amazon_url, parse_amazon_product

FIXTURE = Path(__file__).parent / "fixtures" / "amazon_one_time_sample.html"
URL = "https://www.amazon.com.br/dp/B08KK3FB5G"


def test_canonical_url_removes_tracking_parameters():
    asin, canonical = normalize_amazon_url("https://www.amazon.com.br/Example/dp/B08KK3FB5G?tag=example")
    assert asin == "B08KK3FB5G"
    assert canonical == URL


@pytest.mark.parametrize("url", [
    "http://www.amazon.com.br/dp/B08KK3FB5G",
    "https://www.amazon.com.br.evil.example/dp/B08KK3FB5G",
    "https://www.amazon.com/dp/B08KK3FB5G",
    "https://www.amazon.com.br/s?k=shampoo",
    "https://user:password@www.amazon.com.br/dp/B08KK3FB5G",
])
def test_rejects_invalid_urls(url):
    with pytest.raises(ValueError):
        normalize_amazon_url(url)


def test_extracts_one_time_purchase_not_subscription():
    result = parse_amazon_product(FIXTURE.read_text(), URL)
    assert result.status == "ok"
    assert result.price == "35.91"
    assert result.name == "NIVEA Men Deep Comfort, 100ml"
    assert result.availability == "in_stock"


def test_captcha_not_treated_as_product():
    result = parse_amazon_product('<html><form action="/errors_page/validateCaptcha"></form></html>', URL)
    assert result.status == "captcha_required"
    assert result.price is None


def test_no_arbitrary_price_fallback():
    result = parse_amazon_product('<span id="productTitle">Item</span><span class="a-offscreen">R$1,00</span>', URL)
    assert result.status == "price_unavailable"


def test_ambiguous_price_is_rejected():
    html = '<span id="productTitle">Item</span><div id="buybox"><div class="a-accordion-active">' \
           '<span class="a-price"><span class="a-offscreen">R$35,91</span></span>' \
           '<span class="a-price"><span class="a-offscreen">R$40,00</span></span></div></div>'
    result = parse_amazon_product(html, URL)
    assert result.status == "ambiguous_price"
    assert result.price is None


def test_product_with_inactive_captcha_markup_is_not_blocked():
    html = FIXTURE.read_text().replace(
        "</body>", '<form action="/errors_page/validateCaptcha" style="display:none"></form></body>'
    )
    result = parse_amazon_product(html, URL)
    assert result.status == "ok"
    assert result.price == "35.91"
