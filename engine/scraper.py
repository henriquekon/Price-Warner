import json
import re
import httpx
from bs4 import BeautifulSoup
from pathlib import Path
from engine.addons.registry import load_addon
from engine.addons.amazon_parser import parse_amazon_product, normalize_amazon_url
from urllib.parse import urlparse
import time

# Value Transformations
def transform_value(raw, transform: str):
    """Converts raw extracted value to a desired format"""
    if transform is None or raw is None:
        return raw

    if transform == "float":
        if isinstance(raw, (int, float)):
            return float(raw)
        cleaned = re.sub(r"[^\d.,]", "", str(raw))
        if "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif cleaned.count(".") > 1:
            cleaned = cleaned.replace(".", "")
        return float(cleaned)

    if transform == "comma_decimal_to_float":
        cleaned = re.sub(r"[^\d.,]", "", str(raw))
        cleaned = cleaned.replace(".", "").replace(",", ".") if "," in cleaned else cleaned
        return float(cleaned)

    return raw



# Extractions
def extract_json_in_script(soup: BeautifulSoup, strategy: dict):
    """Extracts value from a JSON object embedded in a <script> tag"""
    tag = soup.select_one(strategy["selector"])
    if not tag:
        return None

    try:
        data = json.loads(tag.string)
        if isinstance(data, list):
            data = data[0]
    except (json.JSONDecodeError, TypeError):
        return None

    keys = strategy["json_path"].split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
        
    mapping = strategy.get("map")
    if mapping and isinstance(mapping, dict):
        return mapping.get(current, "unknown")

    return transform_value(current, strategy.get("transform"))


def extract_meta(soup: BeautifulSoup, strategy: dict):
    """Extracts value from a meta tag"""
    tag = soup.find(
        "meta",
        attrs={strategy["attribute"]: strategy["value"]}
    )
    if not tag:
        return None

    raw = tag.get(strategy["extract"])
    return transform_value(raw, strategy.get("transform"))


def extract_css(soup: BeautifulSoup, strategy: dict):
    """Extracts value via CSS selector, with optional regex"""
    tag = soup.select_one(strategy["selector"])
    if not tag:
        return None

    text = tag.get_text(strip=True)

    regex = strategy.get("regex")
    if regex:
        match = re.search(regex, text)
        if not match:
            return None
        text = match.group(0)

    return transform_value(text, strategy.get("transform"))

def extract_css_exists(soup: BeautifulSoup, strategy: dict):
        tag = soup.select_one(strategy["selector"])
        
        contains_text = strategy.get("contains_text")
        if tag and contains_text:
            found = contains_text in tag.get_text()
        else:
            found = tag is not None

        if strategy.get("invert"):
            found = not found

        return strategy.get("true_value", True) if found else strategy.get("false_value", False)


STRATEGY_MAP = {
    "json_in_script": extract_json_in_script,
    "meta": extract_meta,
    "css": extract_css,
    "css_exists": extract_css_exists,
}


def run_strategies(soup: BeautifulSoup, strategies: list):
    """
    Tries each strategy in order and returns the first successful result
    """
    for strategy in strategies:
        stype = strategy.get("type")
        fn = STRATEGY_MAP.get(stype)
        if not fn:
            print(f"[WARN] Unknown strategy type: '{stype}', skipping.")
            continue

        try:
            result = fn(soup, strategy)
        except Exception as e:
            print(f"[WARN] Strategy '{strategy['name']}' failed with error: {e}")
            result = None

        if result is not None:
            return result, strategy["name"]

    return None, None

class AddonScraper:
    def __init__(self, addon_path: str):
        self.addon = load_addon(addon_path)
        self.client = httpx.Client(http2=True, trust_env=False)
        self._last_request_at = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        self.client.close()

    def _make_request(self, url: str) -> httpx.Response:
        cfg = self.addon.get("request", {})
        base = urlparse(self.addon["store"]["base_url"])
        requested = urlparse(url)
        if (requested.scheme != "https" or requested.hostname != base.hostname or
                requested.username or requested.password or requested.port):
            raise ValueError("Request URL must use the addon store's HTTPS hostname")

        limit = max(0.0, float(cfg.get("rate_limit_seconds", 0)))
        if self._last_request_at is not None:
            remaining = limit - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)

        headers = {
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
            "User-Agent": "Price-Warner/0.2 (self-hosted price monitor)",
            **cfg.get("headers", {}),
        }
        timeout = float(cfg.get("timeout", 15))
        self._last_request_at = time.monotonic()
        current_url = url
        for _ in range(6):
            response = self.client.request(
                cfg.get("method", "GET").upper(), current_url, headers=headers,
                timeout=timeout, follow_redirects=False,
            )
            if response.status_code not in (301, 302, 303, 307, 308):
                response.raise_for_status()
                return response
            destination = response.headers.get("location")
            if not destination:
                raise ValueError("Redirect response has no Location header")
            redirected_url = str(response.url.join(destination))
            redirected = urlparse(redirected_url)
            if (redirected.scheme != "https" or redirected.hostname != base.hostname or
                    redirected.username or redirected.password or redirected.port):
                raise ValueError("Redirect target must use the addon store's HTTPS hostname")
            response.close()
            current_url = redirected_url
        raise ValueError("Too many HTTP redirects")

    def scrape(self, url: str) -> dict:
        """
        Main method to scrape a product page and extract price, name, availability, etc.
        """
        print(f"\n[Scraper] Searching: {url}")
        if self.addon.get("parser") == "amazon_br":
            _, url = normalize_amazon_url(url)
        resp = self._make_request(url)
        return self.scrape_html(resp.text, url)

    def scrape_html(self, html: str, url: str) -> dict:
        """Extract product data from supplied HTML without network or persistence."""
        if self.addon.get("parser") == "amazon_br":
            parsed = parse_amazon_product(html, url)
            return {
                "ok": parsed.status == "ok",
                "status": parsed.status,
                "reason": parsed.reason,
                "url": parsed.url,
                "store": self.addon["store"]["id"],
                "store_name": self.addon["store"]["name"],
                "currency": parsed.currency,
                "price": float(parsed.price) if parsed.price is not None else None,
                "product_name": parsed.name,
                "availability": parsed.availability,
                "image_url": None,
                "strategies_used": {"price": parsed.price_source},
            }
        soup = BeautifulSoup(html, "html.parser")

        result = {
            "url": url,
            "store": self.addon["store"]["id"],
            "store_name": self.addon["store"]["name"],
            "currency": self.addon["store"].get("currency", "BRL"),
            "price": None,
            "product_name": None,
            "availability": None,
            "strategies_used": {},
            "ok": False,
        }

        # Price
        price, strat = run_strategies(soup, self.addon["price"]["strategies"])
        result["price"] = price
        result["strategies_used"]["price"] = strat
        print(f"  Price: {price} (via '{strat}')")

        # Product name
        name, strat = run_strategies(soup, self.addon["product_name"]["strategies"])
        result["product_name"] = name
        result["strategies_used"]["product_name"] = strat
        print(f"  Product Name: {name} (via '{strat}')")

        # Availability (optional)
        avail_cfg = self.addon.get("availability")
        if avail_cfg:
            avail, strat = run_strategies(soup, avail_cfg["strategies"])
            result["availability"] = avail
            result["strategies_used"]["availability"] = strat
            print(f"  Availability: {avail} (via '{strat}')")

        # Image
        image_cfg = self.addon.get("product_image")
        image, strat = run_strategies(soup, image_cfg["strategies"]) if image_cfg else (None, None)
        result["image_url"] = image

        result["ok"] = result["price"] is not None
        return result
    
    def search_external(self, query: str) -> list:
        """
        Searches the store externally by parsing HTML elements or embedded 
        JSON structures dynamically defined in the store's addon configuration.
        """
        search_cfg = self.addon.get("search")
        if not search_cfg:
            print(f"[WARN] Store '{self.addon['store']['id']}' does not support external search.")
            return []

        import urllib.parse
        
        query_encoded = urllib.parse.quote(query)
        url = search_cfg["url_template"].format(query=query_encoded)
        
        try:
            resp = self._make_request(url)
            soup = BeautifulSoup(resp.text, "html.parser")
            products_found = []

            for strategy in search_cfg["strategies"]:
                stype = strategy.get("type")
                
                if stype == "json_catalog":
                    tag = soup.select_one(strategy["selector"])
                    if not tag:
                        continue
                        
                    try:
                        catalog_data = json.loads(tag.string)
                    except (json.JSONDecodeError, TypeError):
                        continue
                        
                    keys = strategy["root_json_path"].split(".")
                    for key in keys:
                        if isinstance(catalog_data, dict):
                            catalog_data = catalog_data.get(key, {})
                            
                    if not isinstance(catalog_data, list):
                        continue
                        
                    mapping = strategy["mapping"]
                    
                    for item in catalog_data[:12]:
                        if not isinstance(item, dict):
                            continue
                            
                        raw_name = item.get(mapping["name_key"], "Sem nome")
                        raw_url_node = item.get(mapping["url_key"], "")
                        raw_price = item.get(mapping["price_key"])
                        raw_image = item.get(mapping["image_key"], "")
                        
                        full_url = f"{mapping.get('url_prefix', '')}{raw_url_node}" if raw_url_node else ""
                        full_image = f"{mapping.get('image_prefix', '')}{raw_image}" if raw_image else None
                        
                        try:
                            price_value = float(raw_price) if raw_price is not None else None
                        except ValueError:
                            price_value = None

                        products_found.append({
                            "name": raw_name,
                            "url": full_url,
                            "price": price_value,
                            "image_url": full_image,
                            "store_id": self.addon["store"]["id"]
                        })
                        
                    if products_found:
                        return products_found

                elif stype == "html_cards":
                    cards = soup.select(strategy["card_selector"])
                    if not cards:
                        continue
                        
                    mapping = strategy["mapping"]
                    for card in cards[:12]:
                        aria_info = card.get(mapping["name_source"], "")
                        if not aria_info:
                            continue
                            
                        raw_url = card.get(mapping["url_source"], "")
                        prefix = mapping.get("url_prefix", "")
                        full_url = raw_url if raw_url.startswith("http") else f"{prefix}{raw_url}"
                        
                        img_tag = card.select_one(mapping["image_selector"])
                        image_url = img_tag.get(mapping["image_source"]) if img_tag else None
                        
                        price_match = re.search(mapping["price_regex"], aria_info)
                        price_value = None
                        name_value = aria_info
                        
                        if price_match:
                            raw_price = price_match.group(1)
                            name_value = aria_info.split(price_match.group(0))[0].strip().rstrip(",")
                            try:
                                if "," in raw_price:
                                    raw_price = raw_price.replace(".", "").replace(",", ".")
                                price_value = float(raw_price)
                            except ValueError:
                                price_value = None

                        products_found.append({
                            "name": name_value,
                            "url": full_url,
                            "price": price_value,
                            "image_url": image_url,
                            "store_id": self.addon["store"]["id"]
                        })
                        
                    if products_found:
                        return products_found
                        
            return products_found

        except Exception as e:
            print(f"[ERROR] Failed to perform robust external search: {e}")
            return []