import json
from pathlib import Path

from engine.addon_cli import inspect_html, main


FIXTURE = Path(__file__).parent / "fixtures" / "example_product.html"


def create_addon(tmp_path):
    addon = {
        "store": {"id": "example", "name": "Example", "base_url": "https://example.com", "currency": "BRL"},
        "price": {"strategies": [{"name": "json_price", "type": "json_in_script", "selector": "script[type='application/ld+json']", "json_path": "offers.price", "transform": "float"}]},
        "product_name": {"strategies": [{"name": "json_name", "type": "json_in_script", "selector": "script[type='application/ld+json']", "json_path": "name"}]},
        "availability": {"strategies": [{"name": "json_availability", "type": "json_in_script", "selector": "script[type='application/ld+json']", "json_path": "offers.availability"}]},
        "product_image": {"strategies": [{"name": "json_image", "type": "json_in_script", "selector": "script[type='application/ld+json']", "json_path": "image"}]},
    }
    path = tmp_path / "example.json"
    path.write_text(json.dumps(addon), encoding="utf-8")
    return path, addon


def test_offline_html_extraction(tmp_path):
    _, addon = create_addon(tmp_path)
    result = inspect_html(addon, FIXTURE.read_text(), "https://example.com/monitor")
    assert result["ok"]
    assert result["price"] == 1299.9
    assert result["product_name"] == "Fixture Monitor"
    assert result["strategies_used"]["price"] == "json_price"


def test_validate_and_list(tmp_path, capsys):
    path, _ = create_addon(tmp_path)
    assert main(["validate", str(path)]) == 0
    assert main(["list", "--addons-dir", str(tmp_path)]) == 0
    assert "search=no" in capsys.readouterr().out


def test_test_offline_without_network(tmp_path, capsys, monkeypatch):
    path, _ = create_addon(tmp_path)
    def forbid(*args, **kwargs):
        raise AssertionError("Network must not be accessed")
    monkeypatch.setattr("engine.addon_cli.AddonScraper", forbid)
    assert main(["test", str(path), "https://example.com/monitor", "--html", str(FIXTURE)]) == 0
    assert '"price": 1299.9' in capsys.readouterr().out


def test_rejects_other_domains(tmp_path, capsys):
    path, _ = create_addon(tmp_path)
    assert main(["test", str(path), "https://evil.example/monitor", "--html", str(FIXTURE)]) == 2
    assert "hostname" in capsys.readouterr().err


def test_rejects_invalid_definition(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text("{}", encoding="utf-8")
    assert main(["validate", str(path)]) == 2
    assert "store" in capsys.readouterr().err
