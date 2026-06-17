# Project Rules

## 1. Architecture And Documentation
When changing services, APIs, data models, env vars, deployment, or user-facing workflows, update:

- `ARCHITECTURE.md`
- `PRODUCTION.md`
- `README.md`
- `CHANGELOG.md`

Keep docs concise but current. `PRODUCTION.md` is the single source of truth for environment variables, and `.env.example` must match it.

## 2. Backend Standards
- Backend lives in `backend/` and uses FastAPI, SQLAlchemy 2.0, Alembic, and Pydantic.
- Local database is SQLite. Production database is PostgreSQL.
- All public identifiers are stable opaque codes such as `prd_*`, `ing_*`, `src_*`, and API routes must not expose numeric IDs.
- All datetimes must be timezone-aware UTC values. Use `datetime.now(UTC)`, never `datetime.utcnow()`.
- JSON payloads from external sources must be stored with source provenance and import timestamps.
- Backend changes require pytest coverage in `backend/tests/`.

## 3. Data And Safety Rules
- Product data must be imported automatically from source adapters. Do not manually type product or ingredient records into production seed data.
- Every risk rule must be traceable to a `source_record`, include evidence type and confidence, and avoid diagnosis language.
- Clinical profile attributes may include skin type, hair type, scalp type, age band, allergies, sensitivities, pregnancy/lactation, and known conditions.
- Do not use gender, nationality, ethnicity, or other demographic proxies in scoring unless a future rule has direct cited evidence and product approval.
- Open/crowdsourced product data must be surfaced with confidence and provenance instead of presented as guaranteed truth.

## 4. Frontend Standards
- Frontend lives in `frontend/` and uses React, Vite, TypeScript, TanStack Query, React Router, and plain CSS modules/global CSS.
- The first screen is the scanner workspace, not a marketing landing page.
- Use restrained product UI: dense enough to operate, clear source/status labels, and no medical overclaiming.
- Frontend utility/API changes require Vitest coverage in `frontend/src/__tests__/`.

## 5. Recognition And ML
- The scan pipeline must stay local-first and optional-dependency-safe.
- Barcode, OCR, and embedding providers must fail gracefully if optional ML packages are not installed.
- Paid/cloud ML integrations must be added behind provider interfaces, not hardcoded into routers.

## 6. Verification
Before handing off a meaningful change, run the relevant checks:

- Backend: `cd backend && source .venv/bin/activate && python -m pytest tests -v`
- Frontend: `cd frontend && npm test -- --run && npm run build`
- API smoke: `curl -s http://127.0.0.1:8000/api/v1/health`

If a command cannot be run, document the reason in the final handoff.
