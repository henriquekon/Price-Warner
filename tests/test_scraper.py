import json
from unittest.mock import Mock

import httpx
import pytest
from bs4 import BeautifulSoup

from engine.scraper import AddonScraper, run_strategies, transform_value


@pytest.mark.parametrize("value,expected", [("1.299,90", 1299.90), ("1299.90", 1299.90), ("R$ 2.386,99", 2386.99)])
def test_currency_conversion(value, expected):
    assert transform_value(value, "float") == expected


def test_strategy_fallback():
    soup = BeautifulSoup('<h4 class="price">R$ 1.299,90</h4>', "html.parser")
    result, name = run_strategies(soup, [
        {"name": "missing", "type": "css", "selector": ".not-found"},
        {"name": "price", "type": "css", "selector": "h4.price", "regex": r"[\d.,]+", "transform": "comma_decimal_to_float"},
    ])
    assert result == pytest.approx(1299.90)
    assert name == "price"


def test_addon_request_configuration(tmp_path, monkeypatch):
    config = {"store": {"id": "example", "name": "Example", "base_url": "https://example.com"},
              "request": {"method": "GET", "headers": {"Accept": "text/html"}, "timeout": 7, "rate_limit_seconds": 0}}
    path = tmp_path / "example.json"
    path.write_text(json.dumps(config))
    with AddonScraper(path) as scraper:
        response = httpx.Response(200, request=httpx.Request("GET", "https://example.com/p"), text="ok")
        mock = Mock(return_value=response)
        monkeypatch.setattr(scraper.client, "request", mock)
        assert scraper._make_request("https://example.com/p").text == "ok"
        assert mock.call_args.kwargs["timeout"] == 7
        assert mock.call_args.kwargs["headers"]["Accept"] == "text/html"
        assert mock.call_args.kwargs["follow_redirects"] is False
        with pytest.raises(ValueError):
            scraper._make_request("http://localhost/admin")
        assert mock.call_count == 1
