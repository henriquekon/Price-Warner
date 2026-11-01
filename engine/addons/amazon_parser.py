"""Offline Amazon Brazil product HTML parser.

This module never performs network requests or accesses credentials.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

_ASIN = re.compile(r"^[A-Z0-9]{10}$")
_ASIN_PATH = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:/|$)", re.I)
_PRICE = re.compile(r"R\$\s*([0-9][0-9.]*,[0-9]{2})")


@dataclass(frozen=True)
class AmazonProductResult:
    status: str
    asin: str | None = None
    url: str | None = None
    name: str | None = None
    price: str | None = None
    currency: str = "BRL"
    availability: str = "unknown"
    price_source: str | None = None
    reason: str | None = None
    variants: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_amazon_url(url: str) -> tuple[str, str]:
    """Return (ASIN, canonical URL) for a supported Amazon Brazil product URL."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host not in {"amazon.com.br", "www.amazon.com.br"}:
        raise ValueError("Only HTTPS Amazon Brazil product URLs are supported")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Unexpected credentials or port in product URL")
    match = _ASIN_PATH.search(parsed.path)
    if not match:
        raise ValueError("Amazon product URL must include /dp/ASIN or /gp/product/ASIN")
    asin = match.group(1).upper()
    if not _ASIN.fullmatch(asin):
        raise ValueError("Invalid ASIN")
    return asin, f"https://www.amazon.com.br/dp/{asin}"


def _parse_brl(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    match = _PRICE.search(raw.replace("\xa0", " "))
    if not match:
        return None
    try:
        value = Decimal(match.group(1).replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None
    return value if value > 0 else None


def _single_purchase_prices(soup: BeautifulSoup) -> tuple[set[Decimal], str | None]:
    """Collect only explicit one-time purchase offer price candidates."""
    selectors = (
        "#buybox .a-accordion-active .apex-pricetopay-value .a-offscreen",
        "#buybox .a-accordion-active .a-price:not(.a-text-price) .a-offscreen",
        "#apex_offerDisplay_desktop #corePrice_feature_div .apex-pricetopay-value .a-offscreen",
    )
    for selector in selectors:
        prices: set[Decimal] = set()
        for node in soup.select(selector):
            if node.find_parent(id="subscriptionPrice") or node.find_parent(id="sns-base-price"):
                continue
            if node.find_parent(class_="aok-hidden"):
                continue
            value = _parse_brl(node.get_text(" ", strip=True))
            if value is not None:
                prices.add(value)
        if prices:
            return prices, selector
    return set(), None


def extract_amazon_variants(soup: BeautifulSoup, current_asin: str) -> tuple[dict, ...]:
    """Extract book formats with independent Amazon Brazil product URLs."""
    variants = []
    seen = set()
    for node in soup.select("#formats .swatchElement, #tmmSwatches .swatchElement"):
        link = node.select_one("a")
        label_node = node.select_one(".slot-title")
        if link is None or label_node is None:
            continue
        label = label_node.get_text(" ", strip=True)
        if not label:
            continue
        selected = "selected" in node.get("class", []) or link.get("aria-checked") == "true"
        if selected:
            asin = current_asin
        else:
            href = link.get("href", "")
            match = _ASIN_PATH.search(href)
            if not match:
                continue
            asin = match.group(1).upper()
        if asin in seen or not _ASIN.fullmatch(asin):
            continue
        seen.add(asin)
        price_node = node.select_one(".slot-price [aria-label]")
        indicative_price = _parse_brl(price_node.get("aria-label")) if price_node else None
        variants.append({
            "asin": asin,
            "label": label,
            "url": f"https://www.amazon.com.br/dp/{asin}",
            "selected": selected,
            "display_price": str(indicative_price) if indicative_price is not None else None,
        })
    return tuple(variants) if len(variants) > 1 else ()


def parse_amazon_product(html: str, url: str) -> AmazonProductResult:
    """Parse previously acquired HTML, without fetching or saving anything."""
    asin, canonical = normalize_amazon_url(url)
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    product_node = soup.select_one("#productTitle")
    if not product_node and (
        soup.select_one('form[action*="validateCaptcha"]')
        or soup.select_one('input[name="field-keywords"]')
        or "robot check" in title
    ):
        return AmazonProductResult("captcha_required", asin, canonical, reason="Verification page detected")

    name_node = product_node
    if not name_node:
        return AmazonProductResult("invalid_page", asin, canonical, reason="Product title not found")
    name = name_node.get_text(" ", strip=True)
    if not name:
        return AmazonProductResult("invalid_page", asin, canonical, reason="Product title is empty")

    availability_node = soup.select_one("#availability")
    availability_text = availability_node.get_text(" ", strip=True).lower() if availability_node else ""
    if any(word in availability_text for word in ("indisponível", "fora de estoque", "temporariamente esgotado")):
        availability = "out_of_stock"
    elif "em estoque" in availability_text:
        availability = "in_stock"
    else:
        availability = "unknown"

    variants = extract_amazon_variants(soup, asin)
    prices, source = _single_purchase_prices(soup)
    if len(prices) > 1:
        return AmazonProductResult("ambiguous_price", asin, canonical, name, availability=availability,
                                   reason="Conflicting one-time purchase prices", variants=variants)
    if not prices:
        return AmazonProductResult("price_unavailable", asin, canonical, name, availability=availability,
                                   reason="Reliable one-time purchase price not found", variants=variants)
    price = next(iter(prices))
    return AmazonProductResult("ok", asin, canonical, name, f"{price:.2f}",
                               availability=availability, price_source=source, variants=variants)
