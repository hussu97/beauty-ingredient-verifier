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

EWG Skin Deep is supported as an enrichment source. Import EWG exports through `import-ewg-skin-deep`, or collect local personal-use pages through `scrape-ewg-skin-deep`. Both paths store raw EWG payloads in `source_records`, queryable unmodeled fields in `source_record_facts`, link products and ingredients through source-fusion tables, and expose normalized source attributes/conflicts in product detail and admin source views. Keep EWG-provided values source-separated from Open Beauty Facts so provenance and conflicts remain auditable.

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
| `BPV_EWG_SOURCE_PATH` | Backend jobs | No | unset | Optional default path to an authorized EWG Skin Deep `.json`, `.jsonl`, `.csv`, or `.parquet` export. |
| `BPV_EWG_API_BASE_URL` | Backend jobs | No | unset | Reserved for an authorized EWG API endpoint; file import uses the same normalization path. |
| `BPV_EWG_API_KEY` | Backend jobs | No | unset | Reserved credential for authorized EWG API access. Treat as secret in production. |
| `BPV_EWG_ATTRIBUTION_TEXT` | Backend/frontend | No | `Contains information from EWG Skin Deep.` | Attribution text to show where EWG data is surfaced. |
| `BPV_EWG_USER_AGENT` | Backend jobs | No | `BeautyProductVerifier/0.1 (local-dev@example.com)` | User-Agent for authorized EWG API/file retrieval workflows. |
| `VITE_API_BASE_URL` | Frontend | Yes | `http://127.0.0.1:8000/api/v1` | Backend API base URL. |

## 6. ML Deployment Notes

The free ML stack is best run locally or as a separate batch worker:

- Install backend extras with `python -m pip install -e ".[ml,data]"`.
- For local EWG browser scraping, the scraper prefers **patchright** (a stealth-patched Playwright fork) and falls back to stock Playwright. Install the browser once with `patchright install chrome` (preferred) or `python -m playwright install chromium`.
- EWG fronts Skin Deep with a **Cloudflare Turnstile** challenge. It is environment-scored, so a **cold headless run cannot pass it** — patchright + a real Chrome profile clears it within seconds only when the browser is **headed** (or run under a virtual display such as `xvfb-run -a` on a headless server). The scraper stays still while Turnstile evaluates (scrolling/mouse gestures during evaluation break the auto-pass) and only performs human-like gestures after it clears, which also loads lazy images/ingredients for more accurate extraction.
- Recommended unattended recipe: `xvfb-run -a scrape-ewg-skin-deep --headed --all-categories --user-data-dir storage/ewg-browser-profile --challenge-wait-seconds 60 --delay-seconds 2 ...`. The persistent `--user-data-dir` profile reuses the cleared `cf_clearance` cookie across runs. Keep `--browser-workers` low (1–2) and `--delay-seconds` ≥ 2; hammering the site gets the source IP flagged and raises challenge difficulty. Database imports stay serial regardless of `--browser-workers`.
- **IP reputation is the dominant factor.** When the egress IP has a clean reputation, Turnstile auto-passes (or a single checkbox click clears it) in a few seconds. Once an IP is flagged from repeated automated hits, Turnstile shows the interactive "Verify you are human" checkbox and refuses to pass an automated browser **even with a correct click** — the only remedies are to wait for the reputation to decay (hours) or switch egress IP. For sustained/high-volume collection, route through a clean residential IP with `--proxy http://user:pass@host:port` (HTTP or SOCKS5 supported). The scraper clicks the real Turnstile checkbox element when one is shown, but cannot defeat an IP-level block on its own.
- Set `BPV_ENABLE_OPTIONAL_ML=true`.
- After importing older Open Beauty Facts exports, run `beauty-product-verifier backfill-open-beauty-facts-images` before image indexing if product image coverage looks low.
- Run `beauty-product-verifier import-ewg-skin-deep --source-path /path/to/ewg-export.jsonl --review-threshold 0.82` to ingest authorized EWG products and ingredient concern data. Use `--dry-run` first for a new export shape.
- Run `beauty-product-verifier scrape-ewg-skin-deep --headed --all-categories --max-products 250 --browser-workers 2 --delay-seconds 2 --output-path storage/ewg-scrape.jsonl` for browser-based EWG category collection (wrap in `xvfb-run -a` on a headless host so Turnstile can clear). Use small batches and `--dry-run` when auditing a new page shape.
- Run `beauty-product-verifier apply-product-corrections` after imports when using the built-in source-backed correction library for known incomplete crowdsourced product records.
- Run `index-images --all --batch-size 25 --download-workers 4` after product imports to populate CLIP embeddings.
- Use `index-images --status`, `index-images --pause`, and `index-images --resume` for resumable local or worker runs.
- Prefer parallel downloads over parallel CLIP worker processes for SQLite/local runs. Embedding and writes are intentionally serial to avoid model-memory duplication and SQLite write contention.
- Keep Cloud Run API instances lean unless OCR/CLIP latency is acceptable for uploads.
- Use PostgreSQL plus pgvector later for production vector search; SQLite uses sqlite-vec locally.
