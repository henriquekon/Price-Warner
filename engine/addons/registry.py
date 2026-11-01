"""Validation and discovery for declarative store addons."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit


class AddonValidationError(ValueError):
    """Raised when an addon definition is invalid."""


SUPPORTED_TYPES = {"json_in_script", "meta", "css", "css_exists"}
SEARCH_TYPES = {"json_catalog", "html_cards"}
ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def _required_string(obj, key, context):
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AddonValidationError(f"{context}.{key} must be a nonempty string")
    return value


def _hostname(url, context):
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port is not None):
            raise ValueError("Invalid HTTPS URL")
    except ValueError as exc:
        raise AddonValidationError(f"{context} must be an HTTPS URL without credentials or port") from exc
    return parsed.hostname.lower().rstrip(".")


def _strategies(section, name, types):
    if not isinstance(section, dict) or not isinstance(section.get("strategies"), list) or not section["strategies"]:
        raise AddonValidationError(f"{name}.strategies must be a nonempty list")
    for index, strategy in enumerate(section["strategies"]):
        ctx = f"{name}.strategies[{index}]"
        if not isinstance(strategy, dict):
            raise AddonValidationError(f"{ctx} must be an object")
        _required_string(strategy, "name", ctx)
        kind = _required_string(strategy, "type", ctx)
        if kind not in types:
            raise AddonValidationError(f"{ctx}.type unsupported: {kind}")
        required = {
            "json_in_script": ("selector", "json_path"),
            "meta": ("attribute", "value", "extract"),
            "css": ("selector",),
            "css_exists": ("selector",),
            "json_catalog": ("selector", "root_json_path"),
            "html_cards": ("card_selector",),
        }[kind]
        for field in required:
            _required_string(strategy, field, ctx)
        if kind in SEARCH_TYPES and not isinstance(strategy.get("mapping"), dict):
            raise AddonValidationError(f"{ctx}.mapping must be an object")
        if "regex" in strategy:
            try:
                re.compile(strategy["regex"])
            except (re.error, TypeError) as exc:
                raise AddonValidationError(f"{ctx}.regex is invalid") from exc


def validate_addon(addon):
    """Validate the existing addon v1 contract without modifying its data."""
    if not isinstance(addon, dict):
        raise AddonValidationError("Addon must be a JSON object")
    store = addon.get("store")
    if not isinstance(store, dict):
        raise AddonValidationError("store must be an object")
    store_id = _required_string(store, "id", "store")
    if not ID_PATTERN.fullmatch(store_id):
        raise AddonValidationError("store.id contains unsupported characters")
    _required_string(store, "name", "store")
    base_host = _hostname(_required_string(store, "base_url", "store"), "store.base_url")
    _required_string(store, "currency", "store")
    request = addon.get("request", {})
    if not isinstance(request, dict):
        raise AddonValidationError("request must be an object")
    if request.get("method", "GET").upper() != "GET":
        raise AddonValidationError("Only GET requests are supported")
    if not isinstance(request.get("headers", {}), dict):
        raise AddonValidationError("request.headers must be an object")
    for field, minimum in (("timeout", 0.1), ("rate_limit_seconds", 0)):
        try:
            value = float(request.get(field, 15 if field == "timeout" else 0))
        except (TypeError, ValueError) as exc:
            raise AddonValidationError(f"request.{field} must be numeric") from exc
        if not minimum <= value <= (120 if field == "timeout" else 86400):
            raise AddonValidationError(f"request.{field} is outside the allowed range")
    parser = addon.get("parser")
    if parser is not None and (parser != "amazon_br" or store_id != "amazon_br" or base_host != "www.amazon.com.br"):
        raise AddonValidationError("Unsupported or mismatched addon parser")
    for section in ("price", "product_name"):
        _strategies(addon.get(section), section, SUPPORTED_TYPES)
    for section in ("availability", "product_image"):
        if section in addon:
            _strategies(addon[section], section, SUPPORTED_TYPES)
    if "search" in addon:
        search = addon["search"]
        if not isinstance(search, dict):
            raise AddonValidationError("search must be an object")
        template = _required_string(search, "url_template", "search")
        if template.count("{query}") != 1:
            raise AddonValidationError("search.url_template must contain one {query} placeholder")
        if _hostname(template.replace("{query}", "test"), "search.url_template") != base_host:
            raise AddonValidationError("search must use the store hostname")
        _strategies(search, "search", SEARCH_TYPES)
    return addon


def load_addon(path):
    path = Path(path)
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise AddonValidationError(f"Unable to read addon {path.name}: {exc}") from exc
    validate_addon(data)
    if path.stem != data["store"]["id"]:
        raise AddonValidationError(f"Addon filename must match store.id: {path.name}")
    return data


def discover_addons(directory):
    result = {}
    for path in sorted(Path(directory).glob("*.json")):
        addon = load_addon(path)
        store_id = addon["store"]["id"]
        if store_id in result:
            raise AddonValidationError(f"Duplicate store ID: {store_id}")
        result[store_id] = addon
    return result


def resolve_addon(url, directory):
    """Return a matching addon ID, or None for unsupported hosts."""
    host = _hostname(url, "product URL")
    for store_id, addon in discover_addons(directory).items():
        base_host = _hostname(addon["store"]["base_url"], "store.base_url")
        if host == base_host:
            return store_id
    return None
