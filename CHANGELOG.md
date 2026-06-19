# Changelog

## 2026-06-19

### Backend
- Removed redundant legacy catalog endpoints and helpers superseded by product detail and the unified faceted directory PLP.
- Added production-only Sentry initialization for the FastAPI app with environment, release, trace, and profiling configuration.
- Fixed production profile-vocabulary loading in `POST /risk/evaluate` by vendoring `profile-options.json` into the backend Docker build context and resolving both local and container paths.
- Hardened `POST /risk/evaluate` so PDP risk results still return when optional audit persistence fails, and normalized source-derived rule side-effect metadata before serialization.
- Reworked `POST /products/directory/products` into the unified directory listing endpoint with search, multi-brand filters, multi-category filters, sort, pagination, source/category labels, and brand/category facet counts.
- Reduced PLP query fanout by using SQLAlchemy filtered/grouped queries plus select-in eager loading and batch risk summary calculation for returned page products.
- Added bounded Wayback CDX discovery retries to the EWG importer via `--cdx-timeout` and `--cdx-max-failures`, so archive.org outages abort cleanly and can be resumed instead of hanging indefinitely.

### Frontend
- Removed the obsolete directory group type now that PLP filters use returned facet objects directly.
- Added production-only Sentry initialization for React with a top-level error boundary and trace sample-rate configuration.
- Replaced the old separate brand/category directory selector with a single ecommerce-style PLP containing search, facet filters with counts, sort controls, pagination, product images, source labels, and profile-aware warning badges.

### Docs
- Removed the legacy directory group endpoint from the public API list.
- Documented backend and frontend profile-vocabulary vendoring for isolated production build contexts.
- Documented best-effort PDP risk evaluation audit persistence in README, architecture, and production notes.
- Documented Sentry production DSNs, environment variables, deploy wiring, and default local-disabled behavior.
- Updated README, ARCHITECTURE, and PRODUCTION to document the single PLP endpoint and the new production Sentry configuration.

### Tests
- Added backend coverage that the API Docker-context profile vocabulary matches the shared source vocabulary.
- Added backend regression coverage for risk evaluation when audit persistence fails or source-derived rule side-effect metadata is malformed.
- Added backend and frontend coverage for production-only Sentry initialization and sampling config.
- Added backend coverage for directory filters, sort, selected facets, and facet counts.
- Added frontend coverage for the unified directory API payload and PLP control rendering.

## 2026-06-18

### Backend
- Optimized `sync-local-to-prod` with env-backed defaults, `auto`/`full`/`delta` strategies, timestamp-watermark delta selection after safe full bootstrap, richer per-table run metadata, and PostgreSQL temp-table/COPY bulk upserts.
- Added opt-in target-table watermark fallback for already-bootstrapped production databases that do not yet have `sync_runs` history, avoiding unnecessary full re-upserts after counts are validated.
- Added database indexes on sync watermark timestamp columns so dry-run/apply delta selection avoids full scans on large catalog, source fact, rule, term link, and embedding tables.
- Added `image_embeddings.updated_at` and changed production pgvector refresh to a server-side `INSERT ... SELECT ... ON CONFLICT`, so embedding deltas include refreshed vectors without streaming all vectors through Python.
- Optimized the directory PLP default risk sort to score a bounded candidate window instead of issuing a production-wide product/ingredient/risk-rule aggregate before pagination.
- Widened ingredient display, normalized, INCI, raw product-ingredient, ingredient source external ID, and canonical term slug/label columns to `TEXT` so production PostgreSQL can accept long source-derived catalog text during local-to-prod sync without truncation.
- Changed `source_record_facts` record/field/value lookup from unique to non-unique so multiple product/ingredient-context facts from the same source record are preserved during production sync.
- Added production deployment implementation: API Docker image now installs only serving ML extras, local scraper/indexer pipeline images are split out, and production Compose runs FastAPI, pgvector Postgres, and Caddy on one VM.
- Changed the production API Docker build to preinstall CPU-only Torch and use GitHub Actions Docker cache, avoiding CUDA/NVIDIA image bloat on the single-VM boot disk.
- Fixed the backend deploy workflow to initialize Docker Buildx before using the GitHub Actions cache backend.
- Fixed the backend deploy migration step so the one-off Alembic container cannot consume the remaining SSH script before `docker compose up -d` and health checks run.
- Hardened the backend deploy health loop to validate the HTTP status and ready body while tolerating transient startup connection resets.
- Fixed a shell `pipefail` false negative in the deploy health gate by using a direct body match instead of a `grep -q` pipeline.
- Fixed the SSH deploy health gate to avoid early remote `exit 0` before the here-doc stream is fully consumed.
- Added `sync-local-to-prod` with dry-run/apply/validate-only modes, explicit dependency-ordered catalog/source/embedding table sync, runtime-table exclusions, sync run tracking, and pgvector refresh after embedding sync.
- Added `sync_runs` plus a PostgreSQL `image_embedding_vectors` pgvector side index for production CLIP image matching from synced JSON embeddings.
- Added audit-remediation integrity hardening: SQLite foreign keys are enabled for runtime/test engines, metadata now mirrors migration uniqueness boundaries, and production startup rejects local-only auto-create/demo-bootstrap flags.
- Added an Alembic migration for source-record identity, lookup indexes, product-source-link deduplication, and high-volume search/indexing paths.
- Changed scan uploads to enqueue pending scan jobs with `202 Accepted`; matching now runs in a backend background task and clients poll `GET /scans/{scan_code}`.
- Reworked scan product search to generate indexed DB candidates before fuzzy scoring, removing the old first-500-products matching ceiling.
- Optimized directory product ranking by using database-side coarse risk ordering and bounded profile-aware evaluation windows instead of loading and scoring every product in a group.
- Added session-level importer caches for repeated brand/category/ingredient upserts and narrowed EWG brand-fusion candidate queries with eager-loaded ingredients.
- Added structured logging and guardrails for barcode/OCR/embedding fallbacks, image downloads, sqlite-vec failures, and large vector fallback searches.
- Added audit regression tests for FK pragmas, metadata uniqueness, source-record record-type identity, large-catalog search, failed scan persistence, and async scan enqueue behavior.
- Removed legacy direct EWG ingestion paths (`import-ewg-skin-deep` file/API-style import and `scrape-ewg-skin-deep` Playwright/Selenium browser collection); EWG ingestion now uses the Wayback importer.
- Added EWG/OBF category canonicalization and centralized EWG ingredient-INCI cross-validation so source fusion keeps EWG hazard scores on real Open Beauty Facts-compatible ingredient names.
- Added conservative UPC/EAN/GTIN extraction from archived EWG page metadata or visible labels when present, while preserving barcode-less brand/name/category/ingredient/image matching as the normal EWG path.
- Added source-fusion tables for product/ingredient source links, canonical terms, term aliases, and source-backed product/ingredient term links.
- Added active `import-ewg-wayback` support for EWG Skin Deep archived product and ingredient pages with resumable archive.org collection, product image extraction, brand/name/category/ingredient fuzzy reconciliation, raw source-record storage, canonical term mapping, and conservative EWG concern-rule generation.
- Added queryable `source_record_facts` storage for scraped or imported source fields that are useful but not first-class catalog columns yet.
- Extended product detail, source, and import APIs with source links, normalized attributes, source conflicts, source term summaries, and source-fusion counts.
- Switched text normalization to preserve non-ASCII names while still stripping diacritics, preventing Cyrillic and other non-Latin product names from collapsing to empty normalized values.
- Fixed resumable image indexing so `--all --retry-failed` retries each failed image once per run and exits cleanly when only broken source URLs remain.
- Added `apply-product-corrections` plus a source-backed MAC Cosmetics correction for `prd_7e395068110222`, replacing the truncated Open Beauty Facts `Allerg` ingredient row with the official Fix+ Setting Spray ingredient list.
- Added search support to `GET /products/directory/groups` so lower-volume brands/categories can be found by name.
- Changed the directory products API to return paginated metadata with `items`, `total`, `limit`, and `offset`.
- Added shared controlled profile vocabulary and alias-aware rule matching so source-backed profile values align with selectable UI options.
- Added exhaustive risk-rule/profile vocabulary tests covering every trusted rule profile value, selectable profile option, and alias/product-gate matching fixture.
- Added catalog directory APIs for brand/category groups and profile-aware ranked product summaries without persisting bulk risk evaluations.
- Made profile risk evaluation return computed results even if SQLite is temporarily locked while a background image-indexing job is writing.
- Added resumable image embedding runs with per-batch commits, progress tracking in `storage/image-index-progress.json`, pause/resume controls via `index-images --pause/--resume`, and status reporting via `index-images --status`.
- Added `index-images --download-workers` for safe parallel image download prefetching while keeping CLIP embedding and SQLite writes serial.
- Fixed Open Beauty Facts image URL handling for short product codes and added downloader fallback repair for already-imported split short-code image URLs that returned 404.
- Added nested Open Beauty Facts `images.selected.<kind>.<language>` image parsing, untyped uploaded-image fallback parsing, and a `backfill-open-beauty-facts-images` repair command for already-imported products.
- Backfilled the local database, adding 7,847 product image rows and reducing products with no image row from 4,506 to 491.
- Started the local full pending-image embedding run in a detached `screen` session named `bpv-image-index`.

### Docs
- Reworked production documentation around Vercel frontend, single-VM GCP backend, local canonical scraping/indexing, GitHub Secrets deploy, local-to-prod sync, and backup/restore operations.
- Documented EWG Skin Deep Wayback import operations, source-fusion provenance, environment variables, and admin audit surfaces.
- Documented source-backed product corrections, resumable image indexing operations, and clarified that source-confidence heuristics are not shown in the scanner UI.

### Frontend
- Vendored shared clinical profile options into `frontend/src/data/` so Vercel builds rooted at `frontend/` compile without importing files outside the project root.
- Added API request timeouts, friendly FastAPI error parsing, scan polling for pending jobs, and XHR upload timeout/network handling.
- Debounced admin and directory searches, stopped directory search from auto-ranking arbitrary first results, and surfaced product/risk query errors on scanner and PDP views.
- Added product source chips, normalized attribute chips, and source-conflict rows to product source notes.
- Added canonical term and source-conflict audit sections to the admin sources tab.
- Changed directory brand/category search to query the backend instead of filtering only the initially loaded high-volume groups.
- Swapped scanner steps so upload is Step 2, the harm meter is Step 3, and results remain Step 4.
- Added paginated directory PLP controls with searchable brand/category filters.
- Standardized responsive behavior across scanner, directory, product detail, and admin surfaces for mobile/tablet layouts.
- Removed the extra `Done` action from profile dropdown menus.
- Made the homepage harm meter interactive so selecting a warning level updates the level explanation inline.
- Replaced the homepage harm-meter cards with a compact scale visualization for unknown, minimal, low, moderate, high, and critical warning levels.
- Added scan upload progress for Step 3: exact upload percentage followed by an indeterminate product-matching state while the synchronous scan request is running.
- Removed repeated profile summary copy from scanner, directory, and PDP surfaces because the custom dropdown selections already communicate the active filters.
- Replaced free-text profile inputs with compact custom single/multi-select dropdowns sourced from the shared profile vocabulary.
- Added a user-facing `/directory` PLP for browsing products by brand or category and ranking them by source-backed warnings for the active profile.
- Reworked product detail pages to include editable profile controls and automatically refresh product risk and ingredient warnings.
- Added a homepage harm-meter section explaining unknown, minimal, low, moderate, high, and critical warning levels.

## 2026-06-17

### Backend
- Added FastAPI MVP architecture for catalog, ingredient, risk, scan, import, source, and health APIs.
- Added SQLite/PostgreSQL-ready SQLAlchemy models, Alembic setup, source-backed seed data, import/enrichment/scan services, and CLI command entry points.
- Added free local ML adapters for ZXing-C++ barcode extraction, PaddleOCR text extraction, Sentence Transformers CLIP image embeddings, and optional sqlite-vec indexing.
- Added Open Beauty Facts bulk image URL derivation from raw `images` payloads, so JSONL dump imports populate product image rows.
- Fixed single-command CLI aliases so `import-open-beauty-facts`, `enrich-ingredients`, `index-images`, and `refresh-risk-signals` parse options correctly.
- Replaced starter risk seeds with a source-backed rule library covering FDA allergen classes, AHA/BHA guidance, hair dye/PPD, formaldehyde hair smoothing, skin-lightening hydroquinone/mercury, SCCS concentration-context opinions, AAD pregnancy/retinoid guidance, and EMA retinoid pregnancy precautions.
- Added product metadata filters and ingredient-name pattern expansion to risk evaluation, plus source URLs in matched risk outputs.

### Frontend
- Added React/Vite scanner workspace, result views, database explorer, profile settings, source status, and API utilities.
- Added source links to matched risk warnings in scanner results.
- Redesigned the frontend into a scanner-first flow with profile review, upload, top-match product details, automatic risk evaluation, ingredient-level warning flags, and admin tabs for products, ingredients, sources, and imports.
- Removed ingredient rank from frontend displays and sorted ingredient lists alphabetically.
- Simplified scanner result copy by removing duplicate product-match summaries, ML/match percentage details, and product source-confidence percentages from user-facing product displays.

### Docs
- Added project rules, architecture, production plan, environment template, and local setup instructions.
