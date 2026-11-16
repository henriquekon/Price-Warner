"""Optional, non-persistent Firefox HTML transport for public store pages.

The browser uses ordinary Playwright behavior. It does not import clearance
cookies, solve challenges, or retry access-denied responses.
"""

from dataclasses import dataclass
from threading import BoundedSemaphore
from urllib.parse import urlsplit


_BROWSER_SLOTS = BoundedSemaphore(2)


class BrowserFetchError(RuntimeError):
    """A browser could not retrieve a usable store document."""


@dataclass(frozen=True)
class BrowserHTMLResponse:
    text: str
    status_code: int = 200


class FirefoxHTMLFetcher:
    def __init__(self, expected_host: str, timeout_seconds: float):
        self.expected_host = expected_host
        self.timeout_ms = int(timeout_seconds * 1000)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._slot_acquired = False

    def _validate_url(self, url: str):
        try:
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or parsed.hostname != self.expected_host
                    or parsed.username or parsed.password or parsed.port is not None):
                raise ValueError("Browser navigation must remain on the store HTTPS host")
        except ValueError as exc:
            raise BrowserFetchError("Browser navigation must remain on the store HTTPS host") from exc

    def _start(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserFetchError(
                "Playwright is missing; install the B1.5.1 browser dependencies"
            ) from exc
        if not _BROWSER_SLOTS.acquire(timeout=15):
            raise BrowserFetchError("browser_busy: no browser execution slot available")
        self._slot_acquired = True
        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.firefox.launch(headless=True)
            self._context = self._browser.new_context(locale="pt-BR", accept_downloads=False)
            self._page = self._context.new_page()
            self._page.set_default_timeout(self.timeout_ms)
            self._page.route("**/*", self._guard_navigation)
        except Exception as exc:
            self.close()
            raise BrowserFetchError(
                "Unable to start Firefox; check Playwright browser installation and container permissions"
            ) from exc

    def _guard_navigation(self, route):
        """Prevent document redirects to other hosts or local resources."""
        request = route.request
        if request.is_navigation_request():
            try:
                self._validate_url(request.url)
            except BrowserFetchError:
                route.abort()
                return
        route.continue_()

    def fetch(self, url: str, *, search: bool = False) -> BrowserHTMLResponse:
        self._validate_url(url)
        if self._page is None:
            self._start()
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            response = self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            if response is None:
                raise BrowserFetchError("Browser did not receive a document response")
            self._validate_url(self._page.url)
            if response.status != 200:
                raise BrowserFetchError(f"browser_http_{response.status}: store did not serve an HTML page")
            if search:
                try:
                    self._page.locator('a[data-cy="list-product"][href]').first.wait_for(
                        state="attached", timeout=min(self.timeout_ms, 8000)
                    )
                except PlaywrightTimeout:
                    pass
            html = self._page.content()
            if self._is_challenge(html):
                raise BrowserFetchError("access_denied: browser received a challenge or block page")
            return BrowserHTMLResponse(html)
        except BrowserFetchError:
            raise
        except PlaywrightTimeout as exc:
            raise BrowserFetchError("browser_timeout: navigation exceeded the configured timeout") from exc
        except Exception as exc:
            raise BrowserFetchError(f"browser_navigation_error: {type(exc).__name__}") from exc

    @staticmethod
    def _is_challenge(html: str) -> bool:
        lowered = html[:25000].lower()
        return any(marker in lowered for marker in (
            "<title>just a moment", "<title>attention required",
            "sorry, you have been blocked", "cf-challenge-running",
            "challenge-platform/h/b/orchestrate",
        ))

    def close(self):
        for item in (self._page, self._context, self._browser, self._playwright):
            if item is not None:
                try:
                    if item is self._playwright:
                        item.stop()
                    else:
                        item.close()
                except Exception:
                    pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        if self._slot_acquired:
            self._slot_acquired = False
            _BROWSER_SLOTS.release()
