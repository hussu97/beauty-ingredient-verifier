# Architecture

## Summary

Beauty Product Verifier is a monorepo with a FastAPI backend, a SQLite/PostgreSQL relational database, and a React/Vite frontend. The MVP is local-first: it can run without paid APIs or manual data entry, while keeping provider interfaces ready for cloud ML later.

## Backend

The backend is organized around FastAPI routers:

- `health` - process and database status.
- `catalog` - products, brands, categories, product ingredients, product images, and directory ranking.
- `ingredients` - ingredient lookup and source-backed risk facts.
- `risk` - profile-aware risk evaluation.
- `scan` - image upload, barcode/OCR/matching pipeline, candidates.
- `imports` - import status and dataset counts.
- `sources` - source inventory and provenance.

SQLAlchemy models use code primary keys (`prd_*`, `ing_*`, etc.) and UTC-aware timestamp columns. JSON source payloads are stored as SQLAlchemy JSON locally and can map to PostgreSQL JSONB later.

Clinical profile values are controlled by `shared/profile-options.json`. The frontend renders those values as custom single/multi-select dropdowns, and the backend canonicalizes profile aliases before rule matching so values such as `perfume`, `baby`, `kid`, `natural rubber`, or `MI` resolve to the rule-supported canonical profile terms.

## Database

Core tables:

- `sources`, `source_records`
- `source_record_facts`
- `product_source_links`, `ingredient_source_links`
- `canonical_terms`, `term_aliases`, `product_term_links`, `ingredient_term_links`
- `brands`, `categories`, `products`, `product_categories`, `product_images`
- `ingredients`, `ingredient_synonyms`, `product_ingredients`
- `risk_rules`, `risk_evaluations`
- `scan_jobs`, `scan_candidates`
- `adverse_event_signals`, `image_embeddings`

The schema keeps external records immutable enough for provenance, while normalized tables support search and evaluation.

## Data Pipeline

1. `import-open-beauty-facts` imports beauty product data from Open Beauty Facts bulk exports or a local sample fixture. Product image derivation supports flat `images.front_*` keys, nested `images.selected.<kind>.<language>` records, and conservative untyped uploaded-image fallbacks from Open Beauty Facts exports. Imports also populate source-fusion links and canonical category/data-quality terms for later cross-source reconciliation.
2. `import-ewg-wayback` imports EWG Skin Deep product and ingredient pages from archive.org Wayback captures. It stores raw parsed EWG payloads in `source_records`, links EWG records to products/ingredients, maps EWG product use/form/body-area/certification/concern fields into canonical terms, and deduplicates products by barcode when archived pages expose UPC/EAN/GTIN, then by brand/name/canonical category/ingredient similarity. EWG ingredient rows are cross-validated against packaging INCI text so source fusion uses Open Beauty Facts-compatible ingredient vocabulary while retaining EWG hazard scores. Fields that do not yet have first-class product columns, such as hazard score image alt text, animal-testing policy, concern references, page headings, and archive parse diagnostics, are stored in `source_record_facts`.
3. `backfill-ewg-wayback-images` repairs already-imported EWG products by re-fetching archived product pages and deriving missing `product_images` rows for CLIP indexing.
4. `enrich-ingredients` adds source-backed ingredient metadata and trusted risk rules from public regulatory, scientific, and medical-specialty sources. Rules are expanded onto exact ingredient names and conservative ingredient-name patterns such as fragrance mixtures, then versioned through `source_records`.
5. `refresh-risk-signals` stores public adverse-event signals as weak evidence, not causation.
6. `backfill-open-beauty-facts-images` repairs already-imported products by deriving missing `product_images` rows from stored `source_records.payload` image metadata.
7. `apply-product-corrections` applies source-backed product repairs for known incomplete crowdsourced records, preserving the original source record while pointing corrected product fields and ingredient links at the trusted correction source.
8. `index-images` downloads/caches product images, computes CLIP embeddings with Sentence Transformers when ML extras are installed, stores portable JSON vectors in `image_embeddings`, and mirrors them into sqlite-vec when available. Long indexing runs are resumable: DB image statuses preserve per-image state, `storage/image-index-progress.json` records run progress, and `storage/image-index.pause` lets a running batch pause cleanly. Downloads can be prefetched in parallel with `--download-workers`, while embedding and DB writes stay serial for SQLite/local stability. Failed image retries are tracked within each run so permanently broken source URLs are attempted once per retry run, then left as `download-failed`.

Open Beauty Facts API calls are allowed only for user-triggered, one-off barcode lookups. Bulk ingestion uses exports.

## Recognition Pipeline

The scanner uses progressive matching:

1. Barcode detection through ZXing-C++ bindings when `BPV_ENABLE_OPTIONAL_ML=true`, with filename barcode fallback for deterministic tests.
2. OCR through PaddleOCR when available, with filename text fallback.
3. Fuzzy product search with RapidFuzz and ingredient overlap.
4. CLIP image embeddings through Sentence Transformers against indexed product images.
5. sqlite-vec KNN search locally when installed; Python cosine search over stored JSON vectors is the portable fallback.

Each step contributes reasons and confidence. If confidence is low, the UI shows candidate choices and can still evaluate OCR-detected ingredients.

## Frontend

The frontend is scanner-first. The `/` route keeps the core user flow on one page:

- Review or update the optional clinical profile, with default behavior disclosed.
- Upload a product image and see scan progress. Browser upload progress is exact; product matching is shown as an indeterminate analysis state because `POST /api/v1/scans` is currently synchronous.
- Read the scale-style harm meter; selecting a warning level reveals that level's meaning without adding extra result-dashboard copy.
- Show the single top product match inline.
- Automatically evaluate risk for the matched product and active profile.
- Render product details and an ingredient list that flags matched source-backed issues, side effects, and read-more evidence links.

The `/directory` route is a user-facing PLP for brand/category browsing. It loads brand or category groups, sends group search text to the backend so matches outside the default high-volume group list are discoverable, ranks products within the selected group by source-backed risk summaries for the active profile, and pages results through the `items/total/limit/offset` directory API response. Product detail pages reuse the scanner product-risk panel and include an editable profile form; changing the profile automatically refreshes the product warning summary.

The frontend uses shared responsive rules across scanner, directory, PDP, and admin surfaces: desktop can use split panes and sticky context panels, while tablet/mobile stacks filters before results, keeps controls full-width, and turns product rows into compact two-line/two-column scan-friendly rows.

Database browsing, source inventory, source-fusion term summaries, source-conflict candidates, and import status live under `/admin` tabs so provenance-heavy operations do not compete with the scanner or directory. Product and ingredient detail routes remain available for admin/deep-link usage.

The UI avoids medical certainty. It labels data freshness, matched warnings, and unknown states without exposing internal matching or source-confidence heuristics in the scanner flow.

## Risk Evaluation

Risk rules are ingredient-linked, source-backed, versioned, and traceable to `source_records`. The evaluator supports:

- Clinical profile filters: controlled skin, scalp, age band, allergies, sensitivities, pregnancy/lactation, and conditions.
- Product metadata filters: product/category/name keywords for contexts such as hair dye, hair smoothing, skin lightening, AHA/BHA skin products, eye-area dye products, and leave-on/hair products.
- Source URLs in matched risk outputs, so UI results can link to the rule evidence.

EWG concern-bucket rules are generated conservatively. Numeric EWG scores are not copied into the internal severity scale; instead, concern categories such as allergies/immunotoxicity, irritation, reproductive/developmental toxicity, contamination, use restrictions, cancer, neurotoxicity, and organ-system toxicity are mapped to internal evidence kinds and only activated when the rule has supported profile or product-context applicability.

Rules do not score by gender, nationality, ethnicity, or unsupported demographic assumptions.

Backend tests audit every trusted risk-rule profile value against the shared profile vocabulary, every selectable value against at least one source-backed rule, and every rule value/alias against a matching product fixture.

Directory product ranking uses the same rule matcher as product risk evaluation, but does not persist `risk_evaluations`; persisted evaluations are reserved for explicit product evaluation flows.
