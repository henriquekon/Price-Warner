"""Developer-facing commands for inspecting and testing store addons."""

import argparse
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from engine.addons.registry import AddonValidationError, discover_addons, load_addon
from engine.scraper import AddonScraper, run_strategies

DEFAULT_ADDONS_DIR = Path(__file__).resolve().parent.parent / "addons"


def inspect_html(addon, html, url):
    """Extract fields from supplied HTML without a network request or database write."""
    if addon.get("parser") == "amazon_br":
        from engine.addons.amazon_parser import parse_amazon_product
        parsed = parse_amazon_product(html, url)
        return {
            "ok": parsed.status == "ok",
            "status": parsed.status,
            "reason": parsed.reason,
            "url": parsed.url,
            "store": addon["store"]["id"],
            "currency": parsed.currency,
            "price": float(parsed.price) if parsed.price else None,
            "product_name": parsed.name,
            "availability": parsed.availability,
            "image_url": None,
            "strategies_used": {"price": parsed.price_source},
        }
    soup = BeautifulSoup(html, "html.parser")
    result = {
        "ok": False,
        "url": url,
        "store": addon["store"]["id"],
        "currency": addon["store"]["currency"],
        "price": None,
        "product_name": None,
        "availability": None,
        "image_url": None,
        "strategies_used": {},
    }
    for section, output_field in (
        ("price", "price"),
        ("product_name", "product_name"),
        ("availability", "availability"),
        ("product_image", "image_url"),
    ):
        config = addon.get(section)
        if config is None:
            continue
        value, strategy = run_strategies(soup, config["strategies"])
        result[output_field] = value
        result["strategies_used"][section] = strategy
    price = result["price"]
    result["ok"] = isinstance(price, (float, int)) and not isinstance(price, bool) and price > 0
    return result


def build_parser():
    parser = argparse.ArgumentParser(description="Price-Warner addon developer tools")
    commands = parser.add_subparsers(dest="command", required=True)
    list_cmd = commands.add_parser("list", help="List installed addons")
    list_cmd.add_argument("--addons-dir", type=Path, default=DEFAULT_ADDONS_DIR)
    validate_cmd = commands.add_parser("validate", help="Validate an addon definition")
    validate_cmd.add_argument("addon", type=Path)
    test_cmd = commands.add_parser("test", help="Test product extraction without saving data")
    test_cmd.add_argument("addon", type=Path)
    test_cmd.add_argument("url", help="Product URL (must match the addon hostname)")
    test_cmd.add_argument("--html", type=Path, help="Use a local HTML fixture instead of a network request")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            addons = discover_addons(args.addons_dir)
            if not addons:
                print("No addons found")
            for store_id, addon in addons.items():
                search = "yes" if addon.get("search") else "no"
                print(f"{store_id}\t{addon['store']['name']}\tproduct=yes\tsearch={search}")
            return 0
        addon = load_addon(args.addon)
        if args.command == "validate":
            print(f"Valid addon: {addon['store']['id']} ({args.addon})")
            return 0
        from engine.addons.registry import _hostname
        if _hostname(args.url, "product URL") != _hostname(addon["store"]["base_url"], "store.base_url"):
            raise AddonValidationError("Product URL hostname does not match addon store")
        if args.html:
            result = inspect_html(addon, args.html.read_text(encoding="utf-8"), args.url)
        else:
            with AddonScraper(str(args.addon)) as scraper:
                result = scraper.scrape(args.url)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result["ok"] else 1
    except (AddonValidationError, OSError, ValueError) as exc:
        print(f"Addon error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
