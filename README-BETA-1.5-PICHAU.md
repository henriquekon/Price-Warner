# Price-Warner B1.5: Pichau Brasil

Release version: `1.0.0-beta.6`. This is an incremental patch over B1.4 Stability & Security. It adds **Pichau only**; TerabyteShop, Mercado Livre, Estante Virtual and Shopee remain planned for later releases.

## Integration

- `pichau` is automatically discovered from `addons/pichau.json`, with product monitoring, name search, pagination and image caching/proxy support.
- Product checks use the advertised **Pix price**, not the crossed-out reference price, credit-card price or installment amount. The parser supports both `R$ 1,199.99` and `R$ 1.199,99` formats. If metadata and visible Pix price disagree, it returns `ambiguous_price` with no price and no notification.
- Out-of-stock products return `out_of_stock`, with no active price. In the saved configurable-kit fixture, metadata says `instock` but the actual purchase button is disabled and says "Esgotado". The disabled purchase button takes precedence, preventing false alerts.
- Available configurable kits can be tracked at their advertised **base price** only; this implementation does not select or price custom combinations of individual components.
- The public Pichau search uses 36 items per upstream page. The existing snapshot paging layer adapts it to the Price-Warner UI's configurable page size without skipping or repeating items. The snapshot is cached for five minutes and upstream search requests are spaced at least five seconds apart. If the site changes, search returns an error rather than guessing or bypassing access controls.
- Images use `https://media.pichau.com.br/` and the existing authenticated image proxy/cache. No raw HTML, user cookie, credentials, database, or `.env` file is bundled in the patch.

## Offline verification performed

Compared with the six user-provided product and catalog HTML pages plus two successive search pages:

| Sample | Expected | Extracted |
| --- | --- | --- |
| Pichau Aldrin LP 1TB SSD | Pix R$ 1,199.99, available | R$ 1,199.99, in_stock |
| Kingston NV3 500GB SSD | Pix R$ 1,289.99, available | R$ 1,289.99, in_stock |
| Mancer jacket + mug bundle | sold out | out_of_stock, price None |
| Ryzen 5500F configurable kit | purchase disabled | out_of_stock, price None |
| `memoria ddr5` page 1 | results 1-36 | 36 cards, images, Pix prices |
| `memoria ddr5` page 2 | results 37-72 | 36 cards, images; one sold-out card has no active price |

The Python suite (including B1.5 regressions) passed **131 tests** in the reconstructed worktree used to build the patch. The complete frontend build could **not** be run in that environment because `npm install` could not resolve `registry.npmjs.org`. The patch changes only the frontend version label and uses the existing search/image components. Live network requests from your Fedora or Ubuntu containers remain to be validated.

## Upgrade on Fedora from B1.4

1. Inspect local changes and make a SQLite backup:

```bash
cd ~/Codigos/Price-Warner
git status --short
python3 deploy/scripts/backup_sqlite.py --output-dir "$HOME/price-warner-backups"
```

2. Extract the patch from Downloads and run tests:

```bash
unzip -o ~/Downloads/price-warner-b1.5-pichau.zip
python -m pytest -q tests
python -m engine.addon_cli validate addons/pichau.json
```

3. Recreate the containers without deleting volumes:

```bash
podman-compose -f compose.yaml -f compose.podman.yaml up -d --build
podman-compose -f compose.yaml -f compose.podman.yaml ps
```

4. Test a live product and the name search from the app. For a simple offline parser regression:

```bash
python -m engine.addon_cli test addons/pichau.json \
  "https://www.pichau.com.br/ssd-pichau-aldrin-lp-1tb-m-2-pcie-4-0-leitura-7000mb-s-gravacao-6000mb-s-pch-aldlp-1tb" \
  --html ~/Downloads/pichau-ssd-normal.html
```

Run the same without `--html` for a live product check. If you monitor any previously unavailable item, it will only trigger price alerts after verified stock and Pix prices are found.

**Frontend deployment note:** this patch uses the existing React `Discover` screen. The pre-existing Dockerfile does not itself compile or copy the React frontend into its Python image. If you run a separate Vite frontend, rebuild/restart it as you normally do; if you serve the frontend through another deployment step, keep that step. You can validate its source on Fedora with `cd frontend && npm install && npm run build`. Container rebuild alone does not test the React build.

## Commit

```bash
git add addons/pichau.json engine/addons/pichau_parser.py \
  engine/addons/registry.py engine/scraper.py engine/addon_cli.py \
  main.py frontend/src/App.tsx frontend/package.json \
  tests/test_pichau.py README-BETA-1.5-PICHAU.md
git commit -m "feat(beta): add Pichau price tracking and paged search"
```

After successful testing, push your commit, pull it on Ubuntu and rebuild the services there. Preserve the existing `.env`, SQLite volume, cached images and SMTP key.
