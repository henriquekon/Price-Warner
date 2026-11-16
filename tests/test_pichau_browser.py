"""B1.5.1 browser transport tests without any network or browser process."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from engine.addons.registry import AddonValidationError, validate_addon
from engine.browser_fetch import BrowserFetchError, BrowserHTMLResponse, FirefoxHTMLFetcher
from engine.scraper import AddonScraper
from tests.test_pichau import product_html, URL


ADDON = Path(__file__).resolve().parents[1] / "addons" / "pichau.json"


def fake_firefox(monkeypatch, *, status=200, current_url=URL, html=None):
    import playwright.sync_api as playwright_sync_api

    page = Mock()
    page.url = current_url
    page.goto.return_value = SimpleNamespace(status=status)
    page.content.return_value = html or product_html()
    context = Mock()
    context.new_page.return_value = page
    browser = Mock()
    browser.new_context.return_value = context
    mock_runtime = Mock()
    mock_runtime.firefox.launch.return_value = browser
    handle = Mock()
    handle.start.return_value = mock_runtime
    monkeypatch.setattr(playwright_sync_api, "sync_playwright", lambda: handle)
    return page, context, browser, mock_runtime


def test_browser_transport_is_pichau_only():
    with AddonScraper(ADDON) as scraper:
        assert scraper.addon["request"]["transport"] == "playwright_firefox"
    definition = {
        "store": {"id": "elsewhere", "name": "Elsewhere", "base_url": "https://example.com", "currency": "BRL"},
        "request": {"transport": "playwright_firefox"},
        "price": {"strategies": [{"name": "price", "type": "css", "selector": ".price"}]},
        "product_name": {"strategies": [{"name": "name", "type": "css", "selector": "h1"}]},
    }
    with pytest.raises(AddonValidationError, match="limited to Pichau"):
        validate_addon(definition)


def test_browser_fetcher_headless_response_and_shutdown(monkeypatch):
    page, context, browser, playwright = fake_firefox(monkeypatch)
    fetcher = FirefoxHTMLFetcher("www.pichau.com.br", 30)
    response = fetcher.fetch(URL)
    assert response.status_code == 200
    assert "R$ 1,199.99" in response.text
    playwright.firefox.launch.assert_called_once_with(headless=True)
    browser.new_context.assert_called_once_with(locale="pt-BR", accept_downloads=False)
    page.goto.assert_called_once_with(URL, wait_until="domcontentloaded", timeout=30000)
    fetcher.close()
    assert page.close.called and context.close.called and browser.close.called


def test_browser_rejects_non_store_navigation_and_redirect(monkeypatch):
    page, *_ = fake_firefox(monkeypatch, current_url="https://127.0.0.1/private")
    fetcher = FirefoxHTMLFetcher("www.pichau.com.br", 20)
    with pytest.raises(BrowserFetchError, match="store HTTPS host"):
        fetcher.fetch("https://example.net/test")
    assert page.goto.call_count == 0
    with pytest.raises(BrowserFetchError, match="store HTTPS host"):
        fetcher.fetch(URL)
    fetcher.close()


def test_browser_fail_closed_on_403_and_challenge(monkeypatch):
    fake_firefox(monkeypatch, status=403)
    fetcher = FirefoxHTMLFetcher("www.pichau.com.br", 20)
    with pytest.raises(BrowserFetchError, match="browser_http_403"):
        fetcher.fetch(URL)
    fetcher.close()

    fake_firefox(monkeypatch, html="<html><head><title>Just a moment...</title></head></html>")
    fetcher = FirefoxHTMLFetcher("www.pichau.com.br", 20)
    with pytest.raises(BrowserFetchError, match="access_denied"):
        fetcher.fetch(URL)
    fetcher.close()


def test_browser_search_waits_for_cards(monkeypatch):
    page, *_ = fake_firefox(monkeypatch)
    fetcher = FirefoxHTMLFetcher("www.pichau.com.br", 25)
    fetcher.fetch("https://www.pichau.com.br/search?q=ssd&page=1", search=True)
    page.locator.assert_called_once_with('a[data-cy="list-product"][href]')
    page.locator.return_value.first.wait_for.assert_called_once_with(state="attached", timeout=8000)
    fetcher.close()


def test_pichau_scraper_uses_browser_but_other_stores_keep_httpx(monkeypatch):
    seen = []

    class FakeFetcher:
        def __init__(self, host, timeout):
            seen.append((host, timeout))
        def fetch(self, url, *, search=False):
            seen.append((url, search))
            return BrowserHTMLResponse(product_html())
        def close(self):
            seen.append("closed")

    monkeypatch.setattr("engine.browser_fetch.FirefoxHTMLFetcher", FakeFetcher)
    monkeypatch.setattr("engine.scraper._pace_browser_host", lambda *_: None)
    with AddonScraper(ADDON) as scraper:
        result = scraper.scrape(URL)
        assert result["price"] == pytest.approx(1199.99)
        assert result["availability"] == "in_stock"
    assert seen == [("www.pichau.com.br", 30.0), (URL, False), "closed"]

    amazon = ADDON.with_name("amazon_br.json")
    with AddonScraper(amazon) as scraper:
        assert scraper.addon["request"].get("transport", "httpx") == "httpx"
        assert scraper._browser_fetcher is None


def test_browser_transport_rejects_off_site_initial_url(monkeypatch):
    with AddonScraper(ADDON) as scraper:
        with pytest.raises(ValueError, match="store's HTTPS hostname"):
            scraper._make_request("http://127.0.0.1/admin")
        assert scraper._browser_fetcher is None


def test_browser_navigation_route_rejects_redirect_to_other_host(monkeypatch):
    page, *_ = fake_firefox(monkeypatch)
    fetcher = FirefoxHTMLFetcher("www.pichau.com.br", 20)
    fetcher.fetch(URL)
    route_handler = page.route.call_args.args[1]

    external_route = Mock()
    external_route.request.url = "http://127.0.0.1/admin"
    external_route.request.is_navigation_request.return_value = True
    route_handler(external_route)
    external_route.abort.assert_called_once()
    external_route.continue_.assert_not_called()

    asset_route = Mock()
    asset_route.request.url = "https://media.pichau.com.br/image.jpg"
    asset_route.request.is_navigation_request.return_value = False
    route_handler(asset_route)
    asset_route.continue_.assert_called_once()
    fetcher.close()


def test_browser_slots_are_released_after_close(monkeypatch):
    fake_firefox(monkeypatch)
    first = FirefoxHTMLFetcher("www.pichau.com.br", 20)
    first.fetch(URL)
    first.close()
    first.close()
    second = FirefoxHTMLFetcher("www.pichau.com.br", 20)
    second.fetch(URL)
    second.close()


def test_browser_host_pacing_is_shared_by_scraper_instances(monkeypatch):
    from engine import scraper as scraper_module

    scraper_module._BROWSER_LAST_REQUEST.clear()
    clock = [1000.0]
    pauses = []

    monkeypatch.setattr(scraper_module.time, "monotonic", lambda: clock[0])

    def sleep(seconds):
        pauses.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(scraper_module.time, "sleep", sleep)
    scraper_module._pace_browser_host("www.pichau.com.br", 10)
    clock[0] += 2
    scraper_module._pace_browser_host("www.pichau.com.br", 10)
    assert pauses == [8]
    scraper_module._BROWSER_LAST_REQUEST.clear()
