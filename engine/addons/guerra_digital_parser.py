"""Extract Guerra Digital product offers from product-scoped Nuvemshop HTML."""

import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from engine.addons.pichau_parser import parse_brl_price


_HOST = "www.guerradigital.com.br"
_IMAGE_HOST = "acdn-us.mitiendanube.com"
_PRODUCT_PATH = re.compile(r"^/produtos/[^/]+/?$")
_IMAGE_PATH = "/stores/002/025/067/products/"


def _product_path(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != _HOST
                or parts.username or parts.password or parts.port is not None
                or not _PRODUCT_PATH.fullmatch(parts.path)):
            return None
    except ValueError:
        return None
    return parts.path.rstrip("/")


def _image_url(raw):
    if not isinstance(raw, str):
        return None
    candidate = "https:" + raw if raw.startswith("//") else raw
    if candidate.startswith("http://" + _IMAGE_HOST + "/"):
        candidate = "https://" + candidate[len("http://"):]
    try:
        parts = urlsplit(candidate)
        if (parts.scheme != "https" or parts.hostname != _IMAGE_HOST
                or parts.username or parts.password or parts.port is not None
                or not parts.path.startswith(_IMAGE_PATH)):
            return None
    except ValueError:
        return None
    return candidate


def _result(url, status, reason=None, name=None, price=None,
            availability="unknown", image=None, price_source=None, original_price=None):
    return {
        "ok": status in ("ok", "out_of_stock"),
        "status": status,
        "reason": reason,
        "url": url,
        "currency": "BRL",
        "price": price,
        "product_name": name,
        "availability": availability,
        "image_url": image,
        "strategies_used": {"price": price_source},
        "price_kind": "pix_or_boleto",
        "offer_origin": "national",
        "original_price": original_price,
        "variants": [],
    }


def parse_guerra_digital_product(html: str, url: str) -> dict:
    """Read the current visible Pix offer; never use prices from related products."""
    expected_path = _product_path(url)
    if expected_path is None:
        raise ValueError("Invalid Guerra Digital product URL")

    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.select_one('link[rel="canonical"][href]')
    if canonical is None:
        return _result(url, "invalid_page", "Product canonical URL is missing")
    if _product_path(canonical.get("href", "")) != expected_path:
        return _result(url, "product_mismatch", "Canonical URL does not match requested product")

    product = soup.select_one("#single-product.js-product-detail[data-variants]")
    form = soup.select_one('#single-product #product_form[data-store^="product-form-"]')
    title = product.select_one("h1.js-product-name") if product else None
    name = title.get_text(" ", strip=True) if title else None
    if product is None or form is None or not name:
        return _result(url, "invalid_page", "Primary product data was not found")

    try:
        variants = json.loads(product["data-variants"])
    except (TypeError, ValueError):
        return _result(url, "invalid_page", "Product variant data is invalid", name)
    if not isinstance(variants, list) or not variants or any(
        not isinstance(v, dict) for v in variants
    ):
        return _result(url, "invalid_page", "Product has no valid variants", name)
    product_ids = {str(v.get("product_id")) for v in variants}
    form_id = form["data-store"].removeprefix("product-form-")
    if len(product_ids) != 1 or form_id not in product_ids:
        return _result(url, "product_mismatch", "Product and purchase form IDs disagree", name)

    image = None
    for variant in variants:
        image = _image_url(variant.get("image_url"))
        if image:
            break
    if image is None:
        meta = soup.select_one('meta[property="og:image"][content]')
        image = _image_url(meta.get("content")) if meta else None

    cash_element = product.select_one('#price_display[data-product-price]')
    cash_price = (parse_brl_price(cash_element.get_text(" ", strip=True))
                  if cash_element else None)
    compare = product.select_one("#compare_price_display")
    original_price = None
    if compare is not None and "display:none" not in compare.get("style", "").replace(" ", "").lower():
        original_price = parse_brl_price(compare.get_text(" ", strip=True))
        if original_price is not None and cash_price is not None and original_price <= cash_price:
            original_price = None

    stock_values = []
    for variant in variants:
        available = variant.get("available")
        stock = variant.get("stock")
        if not isinstance(available, bool):
            return _result(url, "availability_unknown", "Stock status is missing", name, image=image)
        if isinstance(stock, int) and stock <= 0:
            available = False
        stock_values.append(available)

    buy = form.select_one('[data-store="product-buy-button"]')
    if not buy:
        return _result(url, "availability_unknown", "Purchase button is missing", name, image=image)
    disabled = buy.has_attr("disabled") or "nostock" in buy.get("class", [])
    if not any(stock_values):
        if not disabled:
            return _result(url, "availability_unknown", "Stock and purchase button disagree", name, image=image)
        return _result(url, "out_of_stock", name=name, availability="out_of_stock",
                       image=image, price_source="guerra_stock_override",
                       original_price=original_price)
    if disabled or not all(stock_values):
        return _result(url, "availability_unknown", "Default variant availability is ambiguous", name,
                       image=image)

    price_element = cash_element
    if price_element is None:
        return _result(url, "price_unavailable", "Cash price is missing", name,
                       availability="in_stock", image=image)
    displayed_price = cash_price
    try:
        cents = int(price_element["data-product-price"])
    except (TypeError, ValueError):
        cents = None
    if (displayed_price is None or cents is None or cents <= 0
            or abs(displayed_price - cents / 100) >= 0.01):
        return _result(url, "ambiguous_price", "Visible Pix price and numeric price disagree", name,
                       availability="in_stock", image=image)

    return _result(url, "ok", name=name, price=displayed_price,
                   availability="in_stock", image=image,
                   price_source="guerra_pix_visible", original_price=original_price)
