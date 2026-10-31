import json

import pytest

from engine.addons.registry import (
    AddonValidationError, discover_addons, load_addon, resolve_addon,
    validate_addon,
)


def addon_definition():
    return {
        "store": {"id": "example", "name": "Example", "base_url": "https://example.com", "currency": "BRL"},
        "request": {"method": "GET", "timeout": 15, "rate_limit_seconds": 0},
        "price": {"strategies": [{"name": "price", "type": "css", "selector": ".price"}]},
        "product_name": {"strategies": [{"name": "name", "type": "meta", "attribute": "property", "value": "og:title", "extract": "content"}]},
        "search": {"url_template": "https://example.com/search/{query}", "strategies": [{"name": "list", "type": "json_catalog", "selector": "script#data", "root_json_path": "items", "mapping": {}}]},
    }


def test_validate_existing_format():
    assert validate_addon(addon_definition())["store"]["id"] == "example"


def test_reject_invalid_selector_and_unknown_strategy():
    addon = addon_definition()
    addon["price"]["strategies"][0]["type"] = "eval_python"
    with pytest.raises(AddonValidationError, match="unsupported"):
        validate_addon(addon)


def test_reject_external_search_host():
    addon = addon_definition()
    addon["search"]["url_template"] = "https://attacker.example/search/{query}"
    with pytest.raises(AddonValidationError, match="hostname"):
        validate_addon(addon)


def test_resolve_only_exact_host(tmp_path):
    (tmp_path / "example.json").write_text(json.dumps(addon_definition()))
    assert resolve_addon("https://example.com/p/123", tmp_path) == "example"
    assert resolve_addon("https://example.com.evil.test/p/123", tmp_path) is None
    assert resolve_addon("https://other.example/p/123", tmp_path) is None
    with pytest.raises(AddonValidationError):
        resolve_addon("http://example.com/p/123", tmp_path)
    assert list(discover_addons(tmp_path)) == ["example"]


def test_filename_must_match_id(tmp_path):
    (tmp_path / "wrong.json").write_text(json.dumps(addon_definition()))
    with pytest.raises(AddonValidationError, match="filename"):
        load_addon(tmp_path / "wrong.json")
