import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from engine.addon_cli import inspect_html
from engine.addons.registry import load_addon, AddonValidationError
from engine.scraper import AddonScraper


ADDON = Path(__file__).resolve().parents[1] / "addons" / "amazon_br.json"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "amazon_one_time_sample.html"
URL = "https://www.amazon.com.br/dp/B08KK3FB5G"


def test_addon_is_valid():
    assert load_addon(ADDON)["parser"] == "amazon_br"


def test_offline_scraper_integration():
    with AddonScraper(str(ADDON)) as scraper:
        result = scraper.scrape_html(FIXTURE.read_text(), URL)
    assert result["ok"]
    assert result["price"] == 35.91
    assert result["status"] == "ok"


def test_offline_cli_integration():
    result = inspect_html(load_addon(ADDON), FIXTURE.read_text(), URL)
    assert result["ok"] and result["price"] == 35.91


def test_captcha_is_not_a_valid_price():
    html = '<html><form action="/errors_page/validateCaptcha"><input name="field-keywords"></form></html>'
    with AddonScraper(str(ADDON)) as scraper:
        result = scraper.scrape_html(html, URL)
    assert result["status"] == "captcha_required"
    assert result["price"] is None
    assert not result["ok"]


def test_normalized_url_is_used_for_request(monkeypatch):
    html = FIXTURE.read_text()
    with AddonScraper(str(ADDON)) as scraper:
        mock = Mock(return_value=httpx.Response(200, text=html, request=httpx.Request("GET", URL)))
        monkeypatch.setattr(scraper, "_make_request", mock)
        result = scraper.scrape(URL + "?tag=something")
    assert result["ok"]
    mock.assert_called_once_with(URL)


def test_reject_unknown_parser(tmp_path):
    config = load_addon(ADDON).copy()
    config["parser"] = "unsafe.module:execute"
    path = tmp_path / "amazon_br.json"
    path.write_text(json.dumps(config))
    with pytest.raises(AddonValidationError, match="parser"):
        load_addon(path)
