# Production Runbook

## Target Topology

- Frontend: Vercel project rooted at `frontend/`.
- Backend: one cost-conscious GCP Compute Engine VM in `us-central1` by default.
- Production database: PostgreSQL 16 with pgvector on the same VM.
- Local catalog pipeline: scraper and image-indexer containers run locally against local SQLite, then explicitly sync catalog/source/embedding tables to production Postgres.

Start with an `e2-standard-4` VM or equivalent (**4 vCPU / 16 GB RAM**) and a separate persistent balanced/SSD disk mounted at `/opt/bpv/postgres-data`. Use `/opt/bpv/postgres-data/pgdata` as the Postgres data directory so Postgres does not initialize directly in the mount root. Start at **256 GB** and resize the disk before Postgres reaches sustained storage pressure.

Production does not require GCS in v1. Product images are stored as source URLs in `product_images.url`; local indexing may cache files under `backend/storage/product-images`, but production relies on synced `image_embeddings.vector` plus the Postgres pgvector side index.

## Vercel Frontend

Create the Vercel project `beauty-ingredient-verifier` from `frontend/`.

- Build command: `npm run build`
- Output directory: `dist`
- Framework: Vite
- Env: `VITE_API_BASE_URL=https://<api-domain>/api/v1`

`frontend/vercel.json` rewrites SPA routes to `index.html`. Keep frontend secrets in Vercel only; do not copy backend database or deploy secrets into Vercel. The frontend includes `frontend/src/data/profile-options.json`, a vendored copy of `shared/profile-options.json`, because Vercel builds are rooted at `frontend/`.

The production `/directory` page uses `POST /api/v1/products/directory/products` as the single PLP listing endpoint for search, brand/category filters, sort, pagination, and facet counts. No additional frontend or backend environment variables are required beyond `VITE_API_BASE_URL` and the existing API/database settings below.

## GCP VM Bootstrap

1. Create the VM in `us-central1` unless a cheaper equivalent region is deliberately chosen for the whole stack.
2. Attach and mount the data disk:

```bash
sudo mkdir -p /opt/bpv/postgres-data
sudo chown -R "$USER":"$USER" /opt/bpv
```

3. Install Docker Engine and the Docker Compose plugin.
4. Point DNS for `API_DOMAIN` at the VM static IP.
5. Open ports `80` and `443`; keep API port `8000` bound to localhost only.

The VM runs `docker-compose.prod.yml`:

- `api`: FastAPI with API dependencies, PostgreSQL client support, CLIP image embeddings, and barcode extraction.
- `postgres`: `pgvector/pgvector:pg16` with data on the mounted disk.
- `caddy`: TLS reverse proxy for `API_DOMAIN`.

The API Dockerfile preinstalls CPU-only Torch before `sentence-transformers` so production CLIP serving does not pull CUDA/NVIDIA libraries onto the small VM boot disk.

Production API settings are enforced through `/opt/bpv/.env`:

```text
BPV_ENV=production
BPV_AUTO_CREATE_TABLES=false
BPV_BOOTSTRAP_DEMO_DATA=false
BPV_ENABLE_OPTIONAL_ML=true
BPV_ENABLE_SQLITE_VEC=false
```

## GitHub Actions Deploy

`.github/workflows/backend-deploy.yml` runs backend tests, sets up Docker Buildx with the GitHub Actions cache backend, builds `backend/Dockerfile`, pushes the API image to GHCR, copies deployment files to `/opt/bpv`, writes `/opt/bpv/.env` from GitHub Secrets, runs Alembic through a noninteractive one-off container, restarts Compose, and loops on `GET /api/v1/health` until it sees HTTP 200, with transient startup resets tolerated and service logs on failure.

Required GitHub Secrets:

| Secret | Purpose |
| --- | --- |
| `GCP_VM_HOST` | VM host or IP for SSH. |
| `GCP_VM_USER` | SSH user with Docker access. |
| `GCP_VM_SSH_KEY` | Private deploy key. |
| `GHCR_TOKEN` | Optional package token; `GITHUB_TOKEN` is used when omitted. |
| `BPV_DATABASE_URL` | Production SQLAlchemy URL, e.g. `postgresql+psycopg://bpv:<password>@postgres:5432/beauty_product_verifier`. |
| `BPV_POSTGRES_DB` | Postgres database name. |
| `BPV_POSTGRES_USER` | Postgres user. |
| `BPV_POSTGRES_PASSWORD` | Postgres password. |
| `BPV_POSTGRES_DATA_DIR` | Optional host data path; defaults to `/opt/bpv/postgres-data/pgdata`. |
| `BPV_CORS_ORIGINS` | Comma-separated Vercel origins. |
| `BPV_OPEN_BEAUTY_FACTS_USER_AGENT` | Polite Open Beauty Facts contact UA. |
| `BPV_EWG_USER_AGENT` | Polite EWG/archive import contact UA. |
| `API_DOMAIN` | Backend API domain for Caddy. |
| `ACME_EMAIL` | TLS certificate contact email. |

## Local Scrape And Index

Use local SQLite as the canonical source for scraper/indexer-owned tables.

Scraper container:

```bash
docker compose -f docker-compose.pipeline.yml --profile scraper run --rm scraper \
  import-ewg-wayback --max-products 0 --scrape-ingredients --fetch-workers 8
```

If archive.org CDX discovery is timing out, the importer is resumable; rerun with bounded discovery retries and try again later if it aborts:

```bash
import-ewg-wayback --max-products 0 --no-scrape-ingredients --fetch-workers 4 --request-delay 0.25 --cdx-timeout 30 --cdx-max-failures 2
```

Indexer container:

```bash
docker compose -f docker-compose.pipeline.yml --profile indexer run --rm indexer \
  index-images --all --batch-size 25 --download-workers 4
```

Local product image downloads stay under `backend/storage/product-images`. Production should not write catalog/source/embedding rows except through the sync CLI below.

## Local To Production Sync

Set sync defaults in `backend/.env` on the local operator machine. Keep `BPV_DATABASE_URL` pointed at local SQLite for scraper/indexer commands; `BPV_SYNC_PROD_DATABASE_URL` is the separate reachable production Postgres URL used only by sync.

```bash
BPV_SYNC_LOCAL_DATABASE_URL=sqlite:///./storage/beauty_product_verifier.sqlite3
BPV_SYNC_PROD_DATABASE_URL=postgresql+psycopg://bpv:...@127.0.0.1:5432/beauty_product_verifier
BPV_SYNC_TABLES=all
BPV_SYNC_BATCH_SIZE=500
BPV_SYNC_STRATEGY=auto
```

Run Alembic first, then sync idempotent table upserts. CLI flags override `.env` values:

```bash
cd backend
source .venv/bin/activate
sync-local-to-prod --dry-run
sync-local-to-prod --apply
```

The sync writes `sync_runs` rows in production for applied runs and refreshes the Postgres `image_embedding_vectors` pgvector index after `image_embeddings` are synced. The default `auto` strategy performs a full bootstrap when no prior successful run exists for a table, then selects deltas from `updated_at`, `created_at`, `fetched_at`, or `source_updated_at` where present. Tables without a timestamp continue to full-upsert. PostgreSQL targets use per-batch temporary tables with COPY when the driver supports it.
For laptop-driven syncs into the single-VM Docker stack, connect through a private SSH tunnel or another reachable PostgreSQL URL; the VM `.env` `BPV_DATABASE_URL` uses the Docker-internal `postgres` hostname.
Do not deduplicate `source_record_facts` by record/field/value before sync; repeated facts can carry distinct product, ingredient, or source URL context and are keyed by `fact_code`.

Synced tables, in dependency order:

```text
sources, source_records, brands, categories, products, ingredients,
source_record_facts, product_categories, product_images, ingredient_synonyms,
product_ingredients, product_source_links, ingredient_source_links,
canonical_terms, term_aliases, product_term_links, ingredient_term_links,
risk_rules, adverse_event_signals, image_embeddings
```

Never synced from local to production:

```text
scan_jobs, scan_candidates, risk_evaluations
```

Validate after sync:

```bash
sync-local-to-prod \
  --tables all \
  --validate-only
```

If validation reports row-count mismatches, inspect whether production has stale catalog rows. The v1 sync performs upserts; it does not delete rows missing from local.

## Backup And Restore

Back up the production database before large syncs:

```bash
docker compose --env-file /opt/bpv/.env -f /opt/bpv/docker-compose.prod.yml exec postgres \
  pg_dump -U "$BPV_POSTGRES_USER" "$BPV_POSTGRES_DB" > bpv-prod.sql
```

Restore into a maintenance window:

```bash
cat bpv-prod.sql | docker compose --env-file /opt/bpv/.env -f /opt/bpv/docker-compose.prod.yml exec -T postgres \
  psql -U "$BPV_POSTGRES_USER" "$BPV_POSTGRES_DB"
```

## Environment Variables

`PRODUCTION.md` is the source of truth for env vars; keep `.env.example` and `frontend/.env.example` aligned.

| Variable | Service | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `BPV_APP_NAME` | Backend | No | `Beauty Product Verifier` | Human-readable API name. |
| `BPV_ENV` | Backend | No | `local` | Runtime environment label; production must set `production`. |
| `BPV_DATABASE_URL` | Backend | Yes | `sqlite:///./storage/beauty_product_verifier.sqlite3` | SQLAlchemy URL. Use Postgres in production. |
| `BPV_CORS_ORIGINS` | Backend | Yes in prod | `http://127.0.0.1:5173,http://localhost:5173` | Comma-separated allowed frontend origins. |
| `BPV_STORAGE_DIR` | Backend | No | `./storage` | Upload and local artifact directory. |
| `BPV_AUTO_CREATE_TABLES` | Backend | No | `true` | Local convenience only; production must be `false`. |
| `BPV_BOOTSTRAP_DEMO_DATA` | Backend | No | `true` | Local seed convenience only; production must be `false`. |
| `BPV_OPEN_BEAUTY_FACTS_USER_AGENT` | Backend/jobs | Yes | `BeautyProductVerifier/0.1 (local-dev@example.com)` | Polite Open Beauty Facts UA. |
| `BPV_ENABLE_LIVE_OPEN_BEAUTY_FACTS_LOOKUP` | Backend | No | `true` | Allows one-off barcode lookup during scans. |
| `BPV_ENABLE_OPTIONAL_ML` | Backend/jobs | No | `false` | Enables installed barcode/OCR/embedding providers. Production API sets `true`. |
| `BPV_ENABLE_SQLITE_VEC` | Backend/jobs | No | `true` | SQLite-only vector mirror. Production must be `false`. |
| `BPV_OCR_LANGUAGE` | Backend | No | `en` | PaddleOCR language when OCR deps are installed. |
| `BPV_IMAGE_EMBEDDING_MODEL` | Backend/jobs | No | `sentence-transformers/clip-ViT-B-32` | CLIP/Sentence Transformers model. |
| `BPV_IMAGE_DOWNLOAD_TIMEOUT_SECONDS` | Jobs | No | `20` | Product image download timeout for indexing. |
| `BPV_SYNC_LOCAL_DATABASE_URL` | Jobs | No | none | Local canonical SQLite URL for `sync-local-to-prod`; falls back to `BPV_DATABASE_URL`. |
| `BPV_SYNC_PROD_DATABASE_URL` | Jobs | Yes for sync | none | Reachable production Postgres URL for `sync-local-to-prod`. |
| `BPV_SYNC_TABLES` | Jobs | No | `all` | Comma-separated sync tables or `all`; runtime tables remain blocked. |
| `BPV_SYNC_BATCH_SIZE` | Jobs | No | `500` | Batch size for local-to-prod upserts. |
| `BPV_SYNC_STRATEGY` | Jobs | No | `auto` | One of `auto`, `full`, or `delta`; `auto` full-bootstraps then uses timestamp deltas. |
| `BPV_EWG_ATTRIBUTION_TEXT` | Backend/frontend | No | `Contains information from EWG Skin Deep.` | Attribution text wherever EWG data is surfaced. |
| `BPV_EWG_USER_AGENT` | Jobs | Yes for EWG import | `BeautyProductVerifier/0.1 (local-dev@example.com)` | Polite EWG/archive import UA. |
| `BPV_API_IMAGE` | Compose | Yes in prod | none | GHCR image tag deployed by Actions. |
| `BPV_POSTGRES_DB` | Compose | Yes in prod | `beauty_product_verifier` | Postgres database name. |
| `BPV_POSTGRES_USER` | Compose | Yes in prod | `bpv` | Postgres user. |
| `BPV_POSTGRES_PASSWORD` | Compose | Yes in prod | none | Postgres password. |
| `BPV_POSTGRES_DATA_DIR` | Compose | No | `/opt/bpv/postgres-data/pgdata` | Host path for Postgres data. Use a subdirectory under the mounted disk, not the mount root. |
| `API_DOMAIN` | Caddy | Yes in prod | none | Public API domain. |
| `ACME_EMAIL` | Caddy | Yes in prod | none | ACME/TLS contact email. |
| `VITE_API_BASE_URL` | Frontend | Yes | `http://127.0.0.1:8000/api/v1` | Backend API base URL. |

## Verification

```bash
cd backend && source .venv/bin/activate && python -m pytest tests -v
cd frontend && npm test -- --run && npm run build
curl -s http://127.0.0.1:8000/api/v1/health
```
