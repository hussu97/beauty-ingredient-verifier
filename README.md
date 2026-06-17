# Beauty Product Verifier

A local-first MVP for building an automated beauty product and ingredient database, then evaluating product risk against a clinical user profile from uploaded product images.

## Monorepo Layout

- `backend/` - FastAPI API, SQLite/PostgreSQL data layer, import/enrichment/scan services, CLI commands.
- `frontend/` - React + Vite scanner-first workspace with product directory and admin database/source tabs.
- `shared/profile-options.json` - source-backed clinical profile vocabulary used by both frontend controls and backend rule matching.
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
python -m pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. The scanner is the first screen; brand/category product browsing is available under `http://127.0.0.1:5173/directory`; database, source, and import tools are available under `http://127.0.0.1:5173/admin`. The backend auto-creates the local SQLite schema and demo source-backed records by default.

Profile inputs are controlled custom dropdowns sourced from `shared/profile-options.json`. Free-text profile values from older local storage are canonicalized through aliases when possible and unsupported values are dropped rather than sent to risk rules.

The homepage keeps the consumer flow compact: profile dropdowns, image upload, an interactive scale-style harm meter, and the matched product result. The scan progress bar shows exact browser upload progress and then an indeterminate matching state while the synchronous backend scan pipeline evaluates the image. Directory browsing is searchable, paginated, and uses adaptive layouts for desktop and mobile.

## Free Local ML Stack

The scanner and image indexer now use a free local ML stack when enabled:

- ZXing-C++ for barcode extraction.
- PaddleOCR for product/ingredient text extraction.
- Sentence Transformers CLIP embeddings for image similarity.
- sqlite-vec as an optional local SQLite vector index, with JSON vectors still stored in `image_embeddings`.

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

## API Surface

- `GET /api/v1/health`
- `GET /api/v1/products`
- `GET /api/v1/products/directory/groups` - supports `kind`, optional `q`, and `limit`.
- `POST /api/v1/products/directory/products` - returns `{ items, total, limit, offset }` for paginated PLP views.
- `GET /api/v1/products/{product_code}`
- `GET /api/v1/ingredients`
- `GET /api/v1/ingredients/{ingredient_code}`
- `POST /api/v1/risk/evaluate`
- `POST /api/v1/scans`
- `GET /api/v1/scans/{scan_code}`
- `GET /api/v1/sources`
- `GET /api/v1/imports/status`

## CLI Commands

Install the backend package, then run:

```bash
import-open-beauty-facts --help
beauty-product-verifier backfill-open-beauty-facts-images --help
enrich-ingredients --help
beauty-product-verifier apply-product-corrections --help
index-images --help
refresh-risk-signals --help
beauty-product-verifier --help
```

The Open Beauty Facts importer prefers local bulk files (`.jsonl`, `.jsonl.gz`, `.parquet`) and only uses the live API for one-off barcode lookups during scans.

## Verification

```bash
cd backend && source .venv/bin/activate && python -m pytest tests -v
cd frontend && npm test -- --run && npm run build
```
