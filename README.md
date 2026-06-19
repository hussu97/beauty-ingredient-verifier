# Beauty Product Verifier

A local-first MVP for building an automated beauty product and ingredient database, then evaluating product risk against a clinical user profile from uploaded product images.

## Monorepo Layout

- `backend/` - FastAPI API, SQLite/PostgreSQL data layer, import/enrichment/scan services, CLI commands.
- `frontend/` - React + Vite scanner-first workspace with product directory and admin database/source tabs.
- `.github/workflows/backend-deploy.yml` - backend CI/deploy pipeline that tests, Buildx-builds the API image, pushes GHCR, runs migrations noninteractively, restarts the GCP VM stack, and waits through startup resets for an API health 200.
- `shared/profile-options.json` - source-backed clinical profile vocabulary used by backend rule matching; the frontend vendors the same vocabulary under `frontend/src/data/` for Vercel builds.
- `docs/` - implementation notes and future research.
- `scripts/` - convenience scripts for local development.
- `ARCHITECTURE.md` - system model, data flow, and source strategy.
- `PRODUCTION.md` - Docker, Vercel, and GCP deployment notes plus env vars.

## Local Setup

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,data]"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. The scanner is the first screen; brand/category product browsing is available under `http://127.0.0.1:5173/directory`; database, source, and import tools are available under `http://127.0.0.1:5173/admin`. In local mode, the backend can auto-create the SQLite schema and demo source-backed records. Outside local mode, run Alembic migrations and disable demo bootstrap.

Profile inputs are controlled custom dropdowns sourced from the vendored frontend copy of `shared/profile-options.json`. Free-text profile values from older local storage are canonicalized through aliases when possible and unsupported values are dropped rather than sent to risk rules.

The homepage keeps the consumer flow compact: profile dropdowns, image upload, an interactive scale-style harm meter, and the matched product result. `POST /scans` now enqueues a pending scan and returns immediately; the frontend shows exact browser upload progress, then polls `GET /scans/{scan_code}` while barcode/OCR/CLIP matching runs in a backend background task. Directory browsing is searchable, paginated, and uses adaptive layouts for desktop and mobile.

## Free Local ML Stack

The scanner and image indexer use a free local ML stack when enabled:

- ZXing-C++ for barcode extraction.
- PaddleOCR for product/ingredient text extraction.
- Sentence Transformers CLIP embeddings for image similarity.
- sqlite-vec as an optional local SQLite vector index, with JSON vectors still stored in `image_embeddings`. Python cosine fallback remains available for small local embedding sets; larger embedding tables require sqlite-vec or a future production vector index.

For the ML extras, prefer Python 3.11 or 3.12 because Paddle/Torch wheels often lag the newest Python releases:

```bash
cd backend
python -m pip install -e ".[dev,ml,data]"
export BPV_ENABLE_OPTIONAL_ML=true
index-images --limit 100
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The first OCR/CLIP run downloads model weights to the local model cache. If the extras are not installed, the app keeps working with deterministic filename/barcode fallbacks.

For a resumable full image-indexing run:

```bash
cd backend
BPV_ENABLE_OPTIONAL_ML=true BPV_ENABLE_SQLITE_VEC=true index-images --all --batch-size 25 --download-workers 4
BPV_ENABLE_OPTIONAL_ML=true BPV_ENABLE_SQLITE_VEC=true index-images --status
index-images --pause
index-images --resume
```

Progress is stored in `backend/storage/image-index-progress.json`. The database remains the source of truth for each image through `product_images.embedding_status`, so interrupted runs resume from pending images. `--download-workers` parallelizes only image downloads; embedding and database writes stay serial to avoid loading multiple CLIP models or fighting SQLite write locks.

When `--retry-failed` is used with `--all`, each failed image is retried once per run. Permanently broken source URLs remain `download-failed` instead of being retried forever.

If a bulk import was created before nested Open Beauty Facts image metadata was supported, repair image rows from stored source payloads:

```bash
cd backend
beauty-product-verifier backfill-open-beauty-facts-images
```

If a trusted brand/regulatory source is needed to repair a known incomplete Open Beauty Facts record, apply the source-backed correction library:

```bash
cd backend
beauty-product-verifier apply-product-corrections
```

EWG Skin Deep can be imported as a second catalog/enrichment source through archived Wayback Machine pages:

```bash
cd backend
beauty-product-verifier import-ewg-wayback --max-products 100 --dry-run
beauty-product-verifier import-ewg-wayback --max-products 0 --scrape-ingredients --fetch-workers 8
beauty-product-verifier import-ewg-wayback --max-products 0 --no-scrape-ingredients --fetch-workers 4 --request-delay 0.25 --cdx-timeout 30 --cdx-max-failures 2
beauty-product-verifier backfill-ewg-wayback-images --fetch-workers 8
```

The importer stores raw EWG payloads, links them to products and ingredients, normalizes EWG categories to Open Beauty Facts-compatible canonical slugs, cross-validates structured EWG ingredients against packaging INCI text, preserves EWG ingredient hazard scores, and keeps source conflicts visible in product detail and `/admin/sources`. EWG pages generally do not expose barcodes; if an archived page includes UPC/EAN/GTIN metadata or visible text, it is used, otherwise fusion relies on brand/name/category/ingredient overlap and indexed product images.

Local pipeline containers split heavy dependencies from the production API image:

```bash
docker compose -f docker-compose.pipeline.yml --profile scraper run --rm scraper import-ewg-wayback --max-products 0 --scrape-ingredients --fetch-workers 8
docker compose -f docker-compose.pipeline.yml --profile indexer run --rm indexer index-images --all --batch-size 25 --download-workers 4
```

Local SQLite remains canonical for scraper/indexer-owned catalog data. Push idempotent deltas to production Postgres explicitly:

```bash
cd backend
sync-local-to-prod --dry-run
sync-local-to-prod --apply
```

Set `BPV_SYNC_LOCAL_DATABASE_URL`, `BPV_SYNC_PROD_DATABASE_URL`, `BPV_SYNC_TABLES`, `BPV_SYNC_BATCH_SIZE`, and `BPV_SYNC_STRATEGY` in `backend/.env`, or pass the equivalent CLI flags. Applied syncs are recorded in production `sync_runs`; the default `auto` strategy full-bootstraps a table first, then syncs timestamp deltas where available. Runtime/user tables (`scan_jobs`, `scan_candidates`, `risk_evaluations`) are intentionally excluded.
When syncing from a laptop to the single-VM Docker deployment, use a private SSH tunnel or another reachable PostgreSQL URL because the production `BPV_DATABASE_URL` host `postgres` is Docker-internal.
`source_record_facts` sync by stable `fact_code`; repeated record/field/value facts are preserved when they carry distinct product, ingredient, or source URL context.

## API Surface

- `GET /api/v1/health`
- `GET /api/v1/products`
- `GET /api/v1/products/directory/groups` - legacy brand/category group lookup with `kind`, optional `q`, and `limit`.
- `POST /api/v1/products/directory/products` - unified PLP listing with search, `brand_codes`, `category_codes`, `sort`, pagination, and brand/category facet counts.
- `GET /api/v1/products/{product_code}`
- `GET /api/v1/ingredients`
- `GET /api/v1/ingredients/{ingredient_code}`
- `POST /api/v1/risk/evaluate`
- `POST /api/v1/scans`
- `GET /api/v1/scans/{scan_code}`
- `GET /api/v1/sources`
- `GET /api/v1/sources/terms`
- `GET /api/v1/sources/conflicts`
- `GET /api/v1/imports/status`

## CLI Commands

Install the backend package, then run:

```bash
import-open-beauty-facts --help
import-ewg-wayback --help
backfill-ewg-wayback-images --help
beauty-product-verifier backfill-open-beauty-facts-images --help
enrich-ingredients --help
beauty-product-verifier apply-product-corrections --help
index-images --help
refresh-risk-signals --help
sync-local-to-prod --help
beauty-product-verifier --help
```

`POST /api/v1/scans` returns `202 Accepted` with a pending scan job; clients should poll `GET /api/v1/scans/{scan_code}` until `completed` or `failed`.

The Open Beauty Facts importer prefers local bulk files (`.jsonl`, `.jsonl.gz`, `.parquet`) and only uses the live API for one-off barcode lookups during scans. EWG ingestion uses archive.org Wayback captures; direct EWG API/file import and Playwright browser scraping are not supported paths.

## Verification

```bash
cd backend && source .venv/bin/activate && python -m pytest tests -v
cd frontend && npm test -- --run && npm run build
```

## Deployment

Production v1 uses Vercel for `frontend/` and one GCP Compute Engine VM for the API, Postgres, pgvector, and Caddy TLS. The backend deploy workflow builds the lightweight API image with serving ML dependencies only; scraper/indexer dependencies stay in local pipeline images. See `PRODUCTION.md` for VM sizing, GitHub Secrets, Vercel setup, sync, and backup/restore runbooks.
