"""Conservative TerabyteShop product parsing from product-scoped HTML."""

import json
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from engine.addons.pichau_parser import parse_brl_price


_HOST = "www.terabyteshop.com.br"
_IMAGE_HOST = "img.terabyteshop.com.br"
_PRODUCT_PATH = re.compile(r"^/produto/([1-9][0-9]*)/[^/]+/?$")


def _product_id(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != _HOST
                or parts.username or parts.password or parts.port is not None):
            return None
    except ValueError:
        return None
    match = _PRODUCT_PATH.fullmatch(parts.path)
    return match.group(1) if match else None


def _result(url, status, reason=None, name=None, price=None, availability="unknown",
            image=None, price_source=None, original_price=None):
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


def _product_schema(soup):
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(tag.string or tag.get_text())
        except (TypeError, ValueError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if isinstance(candidate.get("@graph"), list):
                candidates += [part for part in candidate["@graph"] if isinstance(part, dict)]
            kind = candidate.get("@type")
            if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
                return candidate
    return None


def _image_url(soup, schema):
    meta = soup.select_one('meta[property="og:image"][content]')
    options = [meta.get("content") if meta else None]
    if isinstance(schema, dict):
        image = schema.get("image")
        options += image if isinstance(image, list) else [image]
    for option in options:
        if not isinstance(option, str):
            continue
        try:
            parsed = urlsplit(option)
        except ValueError:
            continue
        if (parsed.scheme == "https" and parsed.hostname == _IMAGE_HOST
                and parsed.username is None and parsed.password is None
                and parsed.port is None and parsed.path.startswith("/produto/")):
            return option
    return None


def parse_terabyteshop_product(html: str, url: str) -> dict:
    """Extract the current cash offer without confusing redirects or related products."""
    expected_id = _product_id(url)
    if expected_id is None:
        raise ValueError("Invalid TerabyteShop product URL")
    soup = BeautifulSoup(html, "html.parser")

    canonical = soup.select_one('link[rel="canonical"][href]')
    canonical_url = canonical.get("href", "") if canonical else ""
    if canonical_url and _product_id(canonical_url) != expected_id:
        return _result(url, "product_mismatch", "Page redirected to another product or a category")

    product_id = soup.select_one('input[name="idproduto"][value]')
    if product_id and product_id.get("value") != expected_id:
        return _result(url, "product_mismatch", "Product ID does not match requested URL")

    title = soup.select_one("h1")
    name = title.get_text(" ", strip=True) if title else ""
    if not name or not canonical_url and product_id is None:
        return _result(url, "invalid_page", "Product identity could not be confirmed")

    schema = _product_schema(soup)
    image = _image_url(soup, schema)
    offer = schema.get("offers") if isinstance(schema, dict) else None
    if isinstance(offer, list):
        offer = next((item for item in offer if isinstance(item, dict)
                      and _product_id(str(item.get("url", ""))) == expected_id), None)
    if not isinstance(offer, dict):
        offer = None
    if offer and offer.get("url") and _product_id(str(offer["url"])) != expected_id:
        return _result(url, "product_mismatch", "Offer belongs to another product", name, image=image)

    raw_stock = str(offer.get("availability", "")).split("/")[-1].lower() if offer else ""
    if raw_stock in ("outofstock", "soldout", "discontinued"):
        return _result(url, "out_of_stock", name=name, availability="out_of_stock", image=image,
                       price_source="terabyteshop_stock_override")
    availability = "in_stock" if raw_stock in ("instock", "limitedavailability") else "unknown"

    visible = [parse_brl_price(node.get_text(" ", strip=True))
               for node in soup.select('p.val-prod.valVista')]
    visible = [amount for amount in visible if amount is not None]
    if visible and any(abs(price - visible[0]) > 0.009 for price in visible[1:]):
        return _result(url, "ambiguous_price", "Displayed cash prices disagree", name,
                       availability=availability, image=image)
    visible_price = visible[0] if visible else None
    schema_price = parse_brl_price(offer.get("price")) if offer else None
    if visible_price is not None and schema_price is not None and abs(visible_price - schema_price) > 0.009:
        return _result(url, "ambiguous_price", "Schema and cash prices disagree", name,
                       availability=availability, image=image)

    amount = visible_price if visible_price is not None else schema_price
    if amount is None:
        return _result(url, "price_unavailable", "Cash price was not found", name,
                       availability=availability, image=image)
    if availability != "in_stock":
        return _result(url, "availability_unknown", "Stock could not be confirmed", name,
                       availability=availability, image=image)

    previous = soup.select_one('.prec_parc .precode del')
    original = parse_brl_price(previous.get_text(" ", strip=True)) if previous else None
    if original is not None and original <= amount:
        original = None
    source = ("terabyteshop_cash_verified" if visible_price is not None and schema_price is not None
              else "terabyteshop_cash_visible" if visible_price is not None
              else "terabyteshop_cash_schema")
    return _result(url, "ok", name=name, price=amount, availability=availability,
                   image=image, price_source=source, original_price=original)
