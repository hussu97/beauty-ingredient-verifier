# Changelog

## 2026-06-18

### Backend
- Added source-fusion tables for product/ingredient source links, canonical terms, term aliases, and source-backed product/ingredient term links.
- Added active `import-ewg-skin-deep` support for authorized EWG Skin Deep JSON, JSONL, CSV, and Parquet exports with barcode-first product deduplication, brand/name/category/ingredient fuzzy reconciliation, raw source-record storage, canonical term mapping, and conservative EWG concern-rule generation.
- Added `scrape-ewg-skin-deep`, a Playwright/Chromium local browser scraper for EWG browse/product/ingredient pages with persistent browser profile support, all-category discovery, bounded parallel browser workers, rate limits, challenge detection, optional raw JSONL output, and ingredient-page expansion.
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
- Documented EWG Skin Deep file and browser import operations, source-fusion provenance, Playwright setup, environment variables, and admin audit surfaces.
- Documented source-backed product corrections, resumable image indexing operations, and clarified that source-confidence heuristics are not shown in the scanner UI.

### Frontend
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
