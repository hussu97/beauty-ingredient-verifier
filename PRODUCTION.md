# Production Plan

## 1. Docker

Use Docker Compose locally for PostgreSQL parity and production-like backend startup.

Planned services:

- `api`: FastAPI container running `uvicorn app.main:app`.
- `db`: PostgreSQL 16.
- `frontend`: Vite static build or Vercel-hosted in real production.

Run migrations before serving production traffic:

```bash
cd backend
alembic upgrade head
```

## 2. Free Online Services

- Backend: Render/Railway/Fly.io can run the FastAPI container.
- Database: free-tier PostgreSQL where available.
- Frontend: Vercel with `VITE_API_BASE_URL` pointing at the backend.
- Storage: local disk is fine for local MVP; production should use object storage for uploads/images.

## 3. GCP

- Backend: Cloud Run service from a container image.
- Database: Cloud SQL for PostgreSQL.
- Batch imports: Cloud Run Jobs scheduled by Cloud Scheduler.
- Uploaded images and cached source images: Cloud Storage.
- Secrets: Secret Manager for database URL and future provider keys.

Cloud Run should run with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## 4. Vercel Frontend

Build command:

```bash
npm run build
```

Output directory:

```text
dist
```

Set `VITE_API_BASE_URL` to the deployed backend `/api/v1` base URL.

The Vercel app should route all frontend paths to the Vite app, including `/`, `/directory`, `/products/:productCode`, `/ingredients/:ingredientCode`, and `/admin/*`. The directory PLP calls searchable `GET /products/directory/groups` requests and paginated `POST /products/directory/products` requests on the backend API base.

Keep `shared/profile-options.json` deployed with both frontend and backend source. It is the controlled clinical profile vocabulary for custom dropdown inputs and backend alias matching; deployments should run the backend and frontend tests after changing it.

Profile dropdowns and the harm-meter scale are fully client-side UI behavior; no extra production environment variables are required for those interactions.

The current scan UI can report exact upload progress from the browser. Matching/OCR/embedding work is displayed as an indeterminate progress state until the synchronous `POST /api/v1/scans` response returns. Per-stage backend percentages would require an async scan job or streamed progress endpoint later.

EWG Skin Deep is supported as an enrichment source through archive.org Wayback captures via `import-ewg-wayback`. The importer stores raw parsed EWG payloads in `source_records`, queryable unmodeled fields in `source_record_facts`, links products and ingredients through source-fusion tables, and exposes normalized source attributes/conflicts in product detail and admin source views. Keep EWG-provided values source-separated from Open Beauty Facts so provenance and conflicts remain auditable.

## 5. Environment Variables

| Variable | Service | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `BPV_APP_NAME` | Backend | No | `Beauty Product Verifier` | Human-readable API name. |
| `BPV_ENV` | Backend | No | `local` | Runtime environment label. |
| `BPV_DATABASE_URL` | Backend | Yes | `sqlite:///./storage/beauty_product_verifier.sqlite3` | SQLAlchemy database URL. Use PostgreSQL in production. |
| `BPV_CORS_ORIGINS` | Backend | No | `http://127.0.0.1:5173,http://localhost:5173` | Comma-separated allowed frontend origins. |
| `BPV_STORAGE_DIR` | Backend | No | `./storage` | Upload and local artifact directory. |
| `BPV_AUTO_CREATE_TABLES` | Backend | No | `true` | Local convenience; disable in production and use Alembic. |
| `BPV_BOOTSTRAP_DEMO_DATA` | Backend | No | `true` | Seeds source-backed demo data when database is empty. |
| `BPV_OPEN_BEAUTY_FACTS_USER_AGENT` | Backend | Yes for live lookup | `BeautyProductVerifier/0.1 (local-dev@example.com)` | Required polite User-Agent for Open Beauty Facts API calls. |
| `BPV_ENABLE_LIVE_OPEN_BEAUTY_FACTS_LOOKUP` | Backend | No | `true` | Allows one-off barcode lookup during scans. |
| `BPV_ENABLE_OPTIONAL_ML` | Backend | No | `false` | Enables optional barcode/OCR/embedding providers if installed. |
| `BPV_ENABLE_SQLITE_VEC` | Backend | No | `true` | Mirrors image embeddings into sqlite-vec when SQLite and the extension are available. |
| `BPV_OCR_LANGUAGE` | Backend | No | `en` | PaddleOCR language code. |
| `BPV_IMAGE_EMBEDDING_MODEL` | Backend | No | `sentence-transformers/clip-ViT-B-32` | Sentence Transformers image embedding model. |
| `BPV_IMAGE_DOWNLOAD_TIMEOUT_SECONDS` | Backend | No | `20` | Timeout for caching product images during `index-images`. |
| `BPV_EWG_ATTRIBUTION_TEXT` | Backend/frontend | No | `Contains information from EWG Skin Deep.` | Attribution text to show where EWG data is surfaced. |
| `BPV_EWG_USER_AGENT` | Backend/jobs | No | `BeautyProductVerifier/0.1 (local-dev@example.com)` | Attribution/contact User-Agent for EWG-related import workflows. |
| `VITE_API_BASE_URL` | Frontend | Yes | `http://127.0.0.1:8000/api/v1` | Backend API base URL. |

## 6. ML Deployment Notes

The free ML stack is best run locally or as a separate batch worker:

- Install backend extras with `python -m pip install -e ".[ml,data]"`.
- **EWG path: the Wayback Machine importer.** `beauty-product-verifier import-ewg-wayback --max-products N [--scrape-ingredients --max-ingredients M] [--from-date 2023]` pulls EWG Skin Deep pages from archive.org's mirror over plain HTTP. archive.org is not behind Cloudflare, so there is no Turnstile, no browser, and no egress-IP-reputation problem. EWG Skin Deep is entirely a cosmetics/beauty database, so the CDX index covers product and ingredient pages directly without crawling category listings. Imports are idempotent (keyed by EWG product/ingredient slug), so runs are resumable. Use `--from-date` to prefer recent captures and `--request-delay` to stay polite to archive.org.
- EWG product pages usually do not expose barcodes. The parser uses archived UPC/EAN/GTIN metadata or visible labels when present, then falls back to brand/name/canonical-category/ingredient fusion. Product images from EWG and OBF should be indexed with CLIP so barcode-less scans can still match visually.
- EWG structured ingredients are cross-validated against packaging INCI text before product/ingredient rows are written. This keeps EWG hazard scores attached to real INCI names and prevents page chrome or score labels from polluting source fusion.
- Set `BPV_ENABLE_OPTIONAL_ML=true`.
- After importing older Open Beauty Facts exports, run `beauty-product-verifier backfill-open-beauty-facts-images` before image indexing if product image coverage looks low.
- Run `beauty-product-verifier import-ewg-wayback --max-products 0 --scrape-ingredients --fetch-workers 8` to ingest EWG product and ingredient concern data. Use `--dry-run` first when auditing parser behavior.
- Run `beauty-product-verifier backfill-ewg-wayback-images --fetch-workers 8` if EWG products were imported before image support existed.
- Run `beauty-product-verifier apply-product-corrections` after imports when using the built-in source-backed correction library for known incomplete crowdsourced product records.
- Run `index-images --all --batch-size 25 --download-workers 4` after product imports to populate CLIP embeddings.
- Use `index-images --status`, `index-images --pause`, and `index-images --resume` for resumable local or worker runs.
- Prefer parallel downloads over parallel CLIP worker processes for SQLite/local runs. Embedding and writes are intentionally serial to avoid model-memory duplication and SQLite write contention.
- Keep Cloud Run API instances lean unless OCR/CLIP latency is acceptable for uploads.
- Use PostgreSQL plus pgvector later for production vector search; SQLite uses sqlite-vec locally.
