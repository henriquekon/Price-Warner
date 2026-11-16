"""Conservative Pichau Brasil product extraction from public HTML."""
from decimal import Decimal, InvalidOperation
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup


_PRICE_PATTERN = re.compile(r"(?:R\$\s*)?(\d[\d.,\s\xa0]*)")


def parse_brl_price(raw):
    """Parse BRL amounts in Pichau's 1,234.56 and standard 1.234,56 formats."""
    if not isinstance(raw, (str, int, float, Decimal)) or isinstance(raw, bool):
        return None
    value = str(raw).strip()
    match = _PRICE_PATTERN.search(value)
    if not match:
        return None
    amount = re.sub(r"\s", "", match.group(1))
    if not amount:
        return None
    decimal_separator = None
    if "." in amount or "," in amount:
        last_period = amount.rfind(".")
        last_comma = amount.rfind(",")
        separator_index = max(last_period, last_comma)
        if len(amount) - separator_index - 1 == 2:
            decimal_separator = amount[separator_index]
        elif len(amount) - separator_index - 1 != 3:
            return None
    if decimal_separator == ".":
        normalized = amount.replace(",", "")
        if amount.count(".") != 1:
            normalized = amount.replace(".", "")
            normalized = normalized[:-2] + "." + normalized[-2:]
    elif decimal_separator == ",":
        normalized = amount.replace(".", "").replace(",", ".")
    else:
        normalized = amount.replace(".", "").replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d{2})?", normalized):
        return None
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return None
    if not (Decimal("0") < number <= Decimal("100000000")):
        return None
    return float(number)


def _meta(soup, name=None, prop=None):
    attrs = {"name": name} if name else {"property": prop}
    node = soup.find("meta", attrs=attrs)
    return node.get("content", "").strip() if node else ""


def parse_pichau_product(html: str, url: str) -> dict:
    """Return the primary Pix offer only, never a card price or financing amount."""
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "www.pichau.com.br":
        raise ValueError("Invalid Pichau product URL")
    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.find("link", rel="canonical")
    canonical_url = canonical.get("href", "") if canonical else ""
    if canonical_url:
        target = urlsplit(canonical_url)
        if (target.scheme != "https" or target.hostname != "www.pichau.com.br"
                or target.path.rstrip("/") != parsed_url.path.rstrip("/")):
            return _result(url, "product_mismatch", "Product canonical URL does not match requested product")
    title = soup.select_one("h1")
    name = title.get_text(" ", strip=True) if title else _meta(soup, prop="og:title").removesuffix(" | Pichau")
    if not name:
        return _result(url, "invalid_page", "Pichau product title was not found")
    image = _meta(soup, prop="og:image")
    raw_availability = _meta(soup, name="product:availability").lower()
    if raw_availability in ("outofstock", "out_of_stock"):
        availability = "out_of_stock"
    elif raw_availability in ("instock", "in_stock"):
        availability = "in_stock"
    else:
        availability = "unknown"
    # The builder's disabled purchase button can disagree with product meta tags.
    disabled_purchase = soup.select_one('button[class*="button-builderProductPage"].Mui-disabled')
    if disabled_purchase and "esgotado" in disabled_purchase.get_text(" ", strip=True).lower():
        availability = "out_of_stock"
    meta_price = parse_brl_price(_meta(soup, name="product:price:amount"))
    visible_price = None
    price_node = soup.select_one('[class*="price_vista_price"], [class*="price_vista_value"], [class*="price_vista_valuePix"], [class*="price_vista_number"]')
    if price_node is None:
        for candidate in soup.select('[class*="price_vista"]'):
            if "R$" in candidate.get_text(" ", strip=True):
                price_node = candidate
                break
    if price_node is not None:
        visible_price = parse_brl_price(price_node.get_text(" ", strip=True))
    if availability == "out_of_stock":
        return _result(url, "out_of_stock", None, name, None, availability, image, "stock_override")
    if (meta_price is not None and visible_price is not None
            and abs(meta_price - visible_price) > 0.009):
        return _result(url, "ambiguous_price", "Metadata and displayed Pix price differ",
                       name, None, availability, image)
    price = visible_price if visible_price is not None else meta_price
    if price is None:
        return _result(url, "price_unavailable", "Pix price not found", name, None, availability, image)
    if availability != "in_stock":
        return _result(url, "availability_unknown", "Stock state not confirmed", name, None,
                       availability, image)
    source = "pichau_pix_verified" if meta_price and visible_price else (
        "pichau_pix_visible" if visible_price else "pichau_pix_meta")
    return _result(url, "ok", None, name, price, availability, image, source)


def _result(url, status, reason=None, name=None, price=None, availability="unknown", image=None, source=None):
    return {
        "ok": status in ("ok", "out_of_stock"), "status": status,
        "reason": reason, "url": url, "currency": "BRL", "price": price,
        "product_name": name, "availability": availability,
        "image_url": image, "strategies_used": {"price": source}, "variants": [],
        "price_kind": "pix", "offer_origin": "national",
    }
