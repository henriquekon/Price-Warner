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
    image_url: str | None = None
    offer_origin: str = "unknown"

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


def _amazon_core_offer_prices(soup: BeautifulSoup, current_asin: str) -> set[Decimal]:
    """Read only the active product's core offer, not format or related-item prices."""
    widget = soup.select_one("#corePriceDisplay_desktop_feature_div")
    if widget is None:
        return set()
    owner = (widget.get("data-csa-c-asin") or "").upper()
    if owner and owner != current_asin:
        return set()

    prices: set[Decimal] = set()
    for offer in widget.select(".apex-core-price-identifier"):
        label = offer.select_one("#apex-pricetopay-accessibility-label")
        if label is not None:
            value = _parse_brl(label.get_text(" ", strip=True))
            if value is not None:
                prices.add(value)

        amount = offer.get("data-csa-c-price-to-pay")
        if amount:
            try:
                value = Decimal(str(amount))
            except InvalidOperation:
                value = None
            if value is not None and value.is_finite() and value > 0:
                prices.add(value)

        for node in offer.select(".apex-pricetopay-value .a-offscreen"):
            value = _parse_brl(node.get_text(" ", strip=True))
            if value is not None:
                prices.add(value)
    return prices


def _visible_primary_price(node, current_asin: str) -> Decimal | None:
    """Reject hidden, alternate-format and subscription prices before parsing."""
    for ancestor in (node, *node.parents):
        classes = set(ancestor.get("class", [])) if ancestor.name else set()
        if ("aok-hidden" in classes or "a-text-price" in classes
                or ancestor.get("aria-hidden") == "true"
                or "display:none" in (ancestor.get("style") or "").replace(" ", "").lower()):
            return None
        if ancestor.get("id") in {
            "subscriptionPrice", "sns-base-price", "formats", "tmmSwatches",
            "inline-twister-row-media_format", "usedBuySection",
        }:
            return None
        owner = ancestor.get("data-csa-c-asin")
        if owner and owner.upper() != current_asin:
            return None
    raw = node.get("aria-label") or node.get("content") or node.get_text(" ", strip=True)
    return _parse_brl(raw)


def _single_purchase_prices(soup: BeautifulSoup, current_asin: str) -> tuple[set[Decimal], str | None]:
    """Try classic, current and narrowly scoped fallback selectors.

    Different prices from different layouts are not silently ranked: a contradictory
    page is ambiguous, which is safer for a price alerting application.
    """
    strategies = (
        ("legacy_one_time_purchase", (
            "#buybox .a-accordion-active .apex-pricetopay-value .a-offscreen",
            "#buybox .a-accordion-active .a-price:not(.a-text-price) .a-offscreen",
            "#apex_offerDisplay_desktop #corePrice_feature_div .apex-pricetopay-value .a-offscreen",
        )),
        ("amazon_core_offer_price", ()),
        ("scoped_primary_price", (
            "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
            "#corePrice_feature_div .priceToPay .a-offscreen",
            "#corePrice_feature_div .a-price:not(.a-text-price) .a-offscreen",
            "#price_inside_buybox",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
        )),
    )
    collected: set[Decimal] = set()
    chosen: str | None = None
    for name, selectors in strategies:
        candidates: set[Decimal] = set()
        if name == "amazon_core_offer_price":
            candidates = _amazon_core_offer_prices(soup, current_asin)
        else:
            for selector in selectors:
                for node in soup.select(selector):
                    candidate = _visible_primary_price(node, current_asin)
                    if candidate is not None:
                        candidates.add(candidate)
        if candidates:
            if chosen is None:
                chosen = name
            collected.update(candidates)
    return collected, chosen


def extract_amazon_variants(soup: BeautifulSoup, current_asin: str) -> tuple[dict, ...]:
    """Extract book formats with independent ASINs from old and new twisters."""
    variants: list[dict] = []
    seen: set[str] = set()

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
            match = _ASIN_PATH.search(link.get("href", ""))
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

    for node in soup.select("#inline-twister-row-media_format li[data-asin]"):
        asin = (node.get("data-asin") or "").upper()
        if not _ASIN.fullmatch(asin) or asin in seen:
            continue
        label_node = node.select_one(".swatch-title-text")
        if label_node is None:
            continue
        label = label_node.get_text(" ", strip=True)
        if not label:
            continue
        selected = (
            node.get("data-initiallyselected") == "true"
            or node.select_one(".a-button-selected, input[aria-checked='true']") is not None
        )
        seen.add(asin)
        variants.append({
            "asin": asin,
            "label": label,
            "url": f"https://www.amazon.com.br/dp/{asin}",
            "selected": selected,
            "display_price": None,
        })

    return tuple(variants) if len(variants) > 1 else ()


def extract_amazon_offer_origin(soup: BeautifulSoup) -> str:
    """An import-fees badge proves an international offer; absence proves nothing."""
    badge = soup.select_one("#globalStoreBadgePopoverInsideBuybox_feature_div")
    if badge is None:
        return "unknown"
    main = badge.select_one(".a-section.a-spacing-base")
    if main is None:
        return "unknown"
    visible_parts = []
    for node in main.find_all(string=True):
        if node.parent.name in ("script", "style"):
            continue
        if node.parent.find_parent(class_="a-popover-preload") is not None:
            continue
        text = str(node).strip()
        if text:
            visible_parts.append(text)
    text = " ".join(visible_parts).lower()
    if "tributos de importação" in text or "tributos de importacao" in text:
        return "international"
    return "unknown"


def extract_amazon_image(soup: BeautifulSoup) -> str | None:
    """Find a product image candidate; the addon validates its HTTPS host."""
    image = soup.select_one("#landingImage, #imgTagWrapperId img")
    if image is not None:
        for attribute in ("data-old-hires", "src"):
            value = image.get(attribute)
            if isinstance(value, str) and value.startswith("https://"):
                return value
        dynamic = image.get("data-a-dynamic-image")
        if dynamic:
            try:
                import json
                urls = json.loads(dynamic)
                if isinstance(urls, dict):
                    return next((url for url in urls if url.startswith("https://")), None)
            except (ValueError, TypeError):
                pass
    og_image = soup.select_one('meta[property="og:image"]')
    if og_image is not None:
        value = og_image.get("content")
        if isinstance(value, str) and value.startswith("https://"):
            return value
    return None


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

    image_url = extract_amazon_image(soup)
    availability_node = soup.select_one("#availability")
    availability_text = availability_node.get_text(" ", strip=True).lower() if availability_node else ""
    if any(word in availability_text for word in (
        "não disponível", "indisponível", "fora de estoque", "esgotado",
        "não temos previsão", "nao disponivel", "currently unavailable", "out of stock",
    )):
        availability = "out_of_stock"
    elif "em estoque" in availability_text:
        availability = "in_stock"
    else:
        availability = "unknown"

    variants = extract_amazon_variants(soup, asin)
    offer_origin = extract_amazon_offer_origin(soup)
    if availability == "out_of_stock":
        return AmazonProductResult("out_of_stock", asin, canonical, name, availability=availability,
                                   reason="Product is currently unavailable", variants=variants,
                                   image_url=image_url, offer_origin=offer_origin)
    prices, source = _single_purchase_prices(soup, asin)
    if len(prices) > 1:
        return AmazonProductResult("ambiguous_price", asin, canonical, name, availability=availability,
                                   reason="Conflicting one-time purchase prices", variants=variants,
                                   image_url=image_url, offer_origin=offer_origin)
    if not prices:
        return AmazonProductResult("price_unavailable", asin, canonical, name, availability=availability,
                                   reason="Reliable one-time purchase price not found", variants=variants,
                                   image_url=image_url, offer_origin=offer_origin)
    price = next(iter(prices))
    return AmazonProductResult("ok", asin, canonical, name, f"{price:.2f}",
                               availability=availability, price_source=source, variants=variants,
                               image_url=image_url, offer_origin=offer_origin)
