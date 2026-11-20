# Price-Warner B1.6: TerabyteShop product URL monitoring

Release: `1.0.0-beta.8`. Incremental Git patch on top of B1.5.1 with the server and image-proxy fixes.

## Scope

- New TerabyteShop addon: `addons/terabyteshop.json`.
- Firefox headless transport already used by Pichau, now permitted for `www.terabyteshop.com.br`.
- Product URL monitoring. **No automatic name search or pagination.** The store's current robots.txt disallows `/busca` and some paginated/filter URLs.
- The displayed cash price (Pix or boleto) is used, never the installment price or a crossed-out previous price.
- Product identity, stock availability, and price agreement are checked before accepting data.
- The original/list price is extracted as `original_price` for diagnostics but is not stored as a separate price-history entry.
- Product images use `https://img.terabyteshop.com.br/produto/...` and the existing authenticated `/media/image` cache route. The Vite `/media` proxy fix from B1.5.1 must remain installed.
- No schema migration and no changes to Amazon/KaBuM HTTP or Pichau parsing.

## Validated offline against the supplied November 20, 2026 HTML snapshots

| Case | Result |
| --- | --- |
| Kingston NV3 1 TB, product ID 31564 | R$ 1.199,90 cash, R$ 2.009,90 crossed out; available |
| Biostar RX 580, product ID 27175 | R$ 829,99 cash, R$ 1.198,90 crossed out; available |
| WD SN750 SE 500 GB, product ID 18574 | Browser was redirected to the SSD category. Its HTML is **not a valid out-of-stock product fixture**. The parser returns `product_mismatch` instead of inventing a stock state or recording another product's price |

Out-of-stock detection is implemented for actual product pages with `schema.org/OutOfStock` or equivalent offer availability. It is covered with a synthetic change to a valid product fixture. Real-world unavailable-product behavior still needs a valid product-page capture for confirmation.

## Apply and verify

From the project root on the existing B1.5.1 branch:

```bash
cd ~/Codigos/Price-Warner
git status --short
git apply --check ~/Downloads/price-warner-b1.6-terabyteshop.patch
git apply ~/Downloads/price-warner-b1.6-terabyteshop.patch
python -m pytest -q tests
python -m engine.addon_cli validate addons/terabyteshop.json
```

If `frontend/package-lock.json` exists, synchronize it because the beta version in `frontend/package.json` was updated:

```bash
cd frontend
npm install --package-lock-only --ignore-scripts
cd ..
```

Recreate images only if necessary; the worker mounts `addons/` at runtime but `engine/` is baked into the image:

```bash
podman-compose -f compose.yaml -f compose.podman.yaml up -d --build
```

Test the live product inside the worker and API:

```bash
podman-compose -f compose.yaml -f compose.podman.yaml exec worker \
  python -m engine.addon_cli test addons/terabyteshop.json \
  'https://www.terabyteshop.com.br/produto/31564/ssd-kingston-nv3-1tb-m2-nvme-2280-pcie-40-leitura-6000mbs-e-gravacao-4000mbs-snv3s1000g'
```

Substitute `api` for `worker` to validate the product preview service. From the Vite UI (`http://localhost:5173`), select TerabyteShop, paste the URL and preview the product. Verify the thumbnail is served from `/media/image` (status 200 and an image Content-Type).

Do **not** use `git reset --hard`, `git clean -fd`, or `podman-compose down -v` during patch installation.

## Tests and limits

The test suite covers saved-product HTML snapshots, cash-price reconciliation, canonical/ID mismatch prevention, synthetic stock loss, addon validation, mocked browser fetch, CLI extraction, and the image-proxy/cache path. A mocked image download does not establish that the TerabyteShop CDN will return 200 in the deployed container. Confirm the thumbnail through the actual interface. If it returns 404, capture its status and Content-Type before changing the cache downloader.

There is no guarantee the browser's live access will remain available indefinitely. Browser failures should be recorded without replacing existing price history with another product's price.
