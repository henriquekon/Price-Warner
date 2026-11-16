# Price-Warner B1.5.1: Pichau browser transport

Release: `1.0.0-beta.7`. Install as an **incremental patch over B1.5 Pichau** (`1.0.0-beta.6`). B1.4 by itself is not a sufficient base. This patch does not replace the database or `.env` file.

## Why this hotfix exists

The Pichau parser extracted prices, stock, titles, and images from saved HTML, but the worker received HTTP 403 from the storefront through `httpx`. The user verified on Fedora that both visible Firefox and Playwright Firefox **headless** loaded a Pichau product with HTTP 200 and the correct Pix price. This establishes a promising alternative HTML transport, not a guarantee that the deployment image, future requests, or public search will work.

## Changes

- Select `request.transport: playwright_firefox` **only for Pichau**. Amazon and KaBuM retain their existing HTTP client.
- Use ordinary, headless Playwright Firefox for HTML navigation and reuse one short-lived browser context during a search request. No imported Firefox profile, saved session cookies, custom fingerprinting, challenge solver, captcha bypass, or repeated retries for denial responses.
- Require HTTPS on the exact Pichau hostname, including browser navigations. Reject 403 and challenge responses without using their content as product data.
- Preserve the B1.5 Pix price parser, strict stock checks, catalog extraction, pagination, and image URL validation.
- Limit browser-backed requests to one per 10 seconds per store **within a process** and at most two simultaneous Firefox sessions per process. API and worker are separate processes, so this is not a cross-container distributed rate limit.
- Browser timeouts and access-denied reasons are recorded as failures; they do not create fake price history or price alerts.
- Install Firefox and system libraries during container build. `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` ensures the browser remains readable when Docker/Podman runs with `PUID:PGID` rather than root.

## Fedora / Podman installation

Make a database backup first, after confirming your existing B1.5 deployment is committed or that you are comfortable with your current uncommitted changes:

```bash
cd ~/Codigos/Price-Warner

git status --short
python3 deploy/scripts/backup_sqlite.py --output-dir "$HOME/price-warner-backups"
```

Extract the new archive from Downloads, then validate the code:

```bash
unzip -o ~/Downloads/price-warner-b1.5.1-pichau-browser.zip
python -m pytest -q tests
python -m engine.addon_cli validate addons/pichau.json
```

Rebuild the images. The first build downloads Firefox and required Linux libraries, making it considerably larger and slower than previous builds.

```bash
podman-compose -f compose.yaml -f compose.podman.yaml up -d --build
podman-compose -f compose.yaml -f compose.podman.yaml ps
```

Test the public product page **inside the worker**:

```bash
podman-compose -f compose.yaml -f compose.podman.yaml exec worker \
  python -m engine.addon_cli test \
  addons/pichau.json \
  "https://www.pichau.com.br/ssd-pichau-aldrin-lp-1tb-m-2-pcie-4-0-leitura-7000mb-s-gravacao-6000mb-s-pch-aldlp-1tb"
```

Expected if the container behaves like Fedora headless Firefox: `"ok": true`, `"price": 1199.99`, `"availability": "in_stock"`, and a valid image URL. This expected value comes from the supplied saved HTML and the Fedora test. It is not a promise about live pricing at a later time.

Also verify product preview through the app, because **the API container** now needs the browser as well as the worker. Only deploy to Ubuntu after these live tests succeed on Fedora.

## Ubuntu Server / Docker

After committing and pushing from Fedora, pull the changes on Ubuntu. Keep the SQLite volume and existing configuration:

```bash
cd ~/Price-Warner
sudo docker compose up -d --build
sudo docker compose ps
sudo docker compose exec worker python -m engine.addon_cli validate addons/pichau.json
```

Run the same `engine.addon_cli test` command inside the Ubuntu worker. A headless browser does not require a desktop environment or display server. Keep sufficient free disk space and RAM for a full Firefox process. Playwright's official documentation recommends non-root users for browser-based scraping; the existing Compose user setting is retained.

## Caveats

- **Not live-tested by this patch author inside Docker or Podman.** The tests use browser mocks and real user-provided local HTML. The user's Fedora headless Playwright test has succeeded, but the actual container path is not yet verified.
- Pichau's `robots.txt` currently disallows paths with query parameters (`/*?*`) and `/api/`. B1.5's search integration still uses `/search?q=...`; although parsing and UI pagination are wired, automated live search is **not confirmed as an allowed integration**. Obtain authorization or an approved catalog source before treating automatic search as operational. The present hotfix does not bypass this restriction.
- Image URLs are extracted from the product and search HTML, but image-cache downloads use a separate HTTP client. Actual image proxy/cache success depends on the Pichau media host being accessible and must be checked on Fedora.
- A 403 in Firefox, anti-bot challenge, or rate limit should be treated as a denial, not automatically bypassed or endlessly retried. Browser behavior may change over time.
- The Dockerfile still does not build the React frontend. If you serve React separately, use your existing frontend deployment process. This patch only updates the UI version label.

## Verification performed

- `141 passed` Python tests, including browser lifecycle, headless navigation configuration, hostname enforcement, challenge/403 handling, process-level pacing, and compatibility with other stores.
- Offline replay of all four Pichau product HTML samples: Pix prices R$ 1,199.99 and R$ 1,289.99, plus two out-of-stock results with no active price.
- Offline catalog extraction of two `memoria ddr5` search HTML samples: 36 distinct cards and image URLs per page.
- Syntax compilation and addon schema validation.
- **No build of the actual Docker image or live network request from this patch environment** was performed.

## Suggested commit

```bash
git add Dockerfile requirements.txt addons/pichau.json \
  engine/browser_fetch.py engine/scraper.py engine/addons/registry.py engine/core.py \
  main.py frontend/src/App.tsx frontend/package.json \
  tests/test_pichau_browser.py README-BETA-1.5.1-PICHAU-BROWSER.md

git commit -m "fix(beta): fetch Pichau pages with headless Firefox"
```
