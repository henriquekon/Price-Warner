import json
import re
import httpx
from bs4 import BeautifulSoup
from pathlib import Path
from fake_useragent import UserAgent
from data.models import Store, init_db, SessionLocal, Product, PriceHistory

# Value Transformations
def transform_value(raw, transform: str):
    """Converts raw extracted value to a desired format (e.g. float)."""
    if transform is None or raw is None:
        return raw

    if transform == "float":
        if isinstance(raw, (int, float)):
            return float(raw)
        cleaned = re.sub(r"[^\d.,]", "", str(raw))
        cleaned = cleaned.replace(",", ".")
        return float(cleaned)

    if transform == "comma_decimal_to_float":
        # "R$ 1.299,90" → 1299.90
        cleaned = re.sub(r"[^\d,]", "", str(raw))
        cleaned = cleaned.replace(",", ".")
        return float(cleaned)

    return raw



# Extractions
def extract_json_in_script(soup: BeautifulSoup, strategy: dict):
    """Extracts value from a JSON object embedded in a <script> tag."""
    tag = soup.select_one(strategy["selector"])
    if not tag:
        return None

    try:
        data = json.loads(tag.string)
        if isinstance(data, list):
            data = data[0]
    except (json.JSONDecodeError, TypeError):
        return None

    # Navigates through the JSON using the provided path (e.g. "props.pageProps.productPage.product.price")
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
    """Extracts value from a meta tag (e.g. og:price, product:price:amount)."""
    tag = soup.find(
        "meta",
        attrs={strategy["attribute"]: strategy["value"]}
    )
    if not tag:
        return None

    raw = tag.get(strategy["extract"])
    return transform_value(raw, strategy.get("transform"))


def extract_css(soup: BeautifulSoup, strategy: dict):
    """Extracts value via CSS selector, with optional regex."""
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
        
        # If "contains_text" is specified, check if the tag's text contains that substring
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
    Tries each strategy in order and returns the first successful result along with the strategy name.
    """
    for strategy in strategies:
        stype = strategy.get("type")
        fn = STRATEGY_MAP.get(stype)
        if not fn:
            print(f"  [WARN] Unknown strategy type: '{stype}', skipping.")
            continue

        try:
            result = fn(soup, strategy)
        except Exception as e:
            print(f"  [WARN] Strategy '{strategy['name']}' failed with error: {e}")
            result = None

        if result is not None:
            return result, strategy["name"]

    return None, None

class AddonScraper:
    def __init__(self, addon_path: str):
        init_db()
        with open(addon_path, "r", encoding="utf-8") as f:
            self.addon = json.load(f)
        self.ua = UserAgent()
        self.client = httpx.Client(http2=True, timeout=15)

    def save_to_db(self, scrape_result: dict):
        session = SessionLocal()
        try:
            store = session.query(Store).filter(Store.id == scrape_result["store"]).first()
            if not store:
                store = Store(
                    id=scrape_result["store"],
                    name=scrape_result["store_name"]
                )
                session.add(store)
                session.commit()
                session.refresh(store)

            product = session.query(Product).filter(Product.url == scrape_result["url"]).first()
            
            if not product:
                product = Product(
                    name=scrape_result["product_name"],
                    url=scrape_result["url"],
                    store_id=store.id
                )
                session.add(product)
                session.commit()
                session.refresh(product)

            new_history = PriceHistory(
                product_id=product.id,
                price=scrape_result["price"],
                availability=scrape_result["availability"] or "unknown",
                strategy_used=str(scrape_result["strategies_used"].get("price"))
            )
            session.add(new_history)
            session.commit()
            print(f"  [DB] Data saved successfully for product ID: {product.id}")
            
        except Exception as e:
            session.rollback()
            print(f"  [ERROR] Failed to save to database: {e}")
        finally:
            session.close()

    def _make_request(self, url: str) -> httpx.Response:
        cfg = self.addon.get("request", {})
        headers = cfg.get("headers", {})
        headers["User-Agent"] = self.ua.random

        timeout = cfg.get("timeout", 15)

        resp = self.client.get(url, follow_redirects=True)
        resp.raise_for_status()
        return resp

    def scrape(self, url: str) -> dict:
        """
        Main method to scrape a product page and extract price, name, availability, etc.
        """
        print(f"\n[Scraper] Searching: {url}")
        resp = self._make_request(url)
        soup = BeautifulSoup(resp.text, "html.parser")

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

        result["ok"] = result["price"] is not None
        return result



# Quick CLI test
if __name__ == "__main__":
    import sys

    addon_path = sys.argv[1] if len(sys.argv) > 1 else "addons/kabum.json"
    url = sys.argv[2] if len(sys.argv) > 2 else (
        "https://www.kabum.com.br/produto/463543/placa-de-video-rx-7600-series-graphics-cards-xfx-amd-radeon-8gb-gddr6-rx-76pqickby"
    )

    scraper = AddonScraper(addon_path)
    data = scraper.scrape(url)

    if data["ok"]:
        scraper.save_to_db(data)

    print("\n──────────────────────────────")
    print("Final result:")
    print(json.dumps(data, indent=2, ensure_ascii=False))