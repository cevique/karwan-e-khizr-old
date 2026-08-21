# AGENTS.md — Karwan-e-Khizr

Public-transit journey-planning app (multi-leg journey search + realtime vehicle positions + recommendation) for Islamabad/Rawalpindi. Hackathon prototype: vehicle GPS is simulated, payments mocked — every external system sits behind a swappable provider interface.

Doc map: root `README.md` = original architecture plan (partly aspirational — e.g. it names `/mobile`; the real code is `backend/`). `backend/plan.md` = current master implementation blueprint. `backend/docs/` = transit-data research source of truth (`transit_data.json`, `DATA_GAPS.md`). The repo doubles as an Obsidian vault (`.obsidian/`, `plans and queries/` = product notes).

## Ownership & branches

- `backend/` — FastAPI + PostgreSQL/PostGIS service. **Owned by the backend teammate, works on `main`.**
- `frontend/` — React Native + Expo + TypeScript app (empty scaffold today). **We work on `v0.1`.**

**The ownership boundary is absolute:** never modify anything under `/backend` during frontend work unless the user explicitly requests a backend change in that message. This includes "helpful" cleanup, refactors, dependency bumps, and fixing things that look wrong. If a backend change seems necessary: don't make it — explain what and why, then wait for approval.

Git safety: no force-push; no reset/rebase/rewrite of anything not purely local frontend work; keep commits scoped to `frontend/` (plus this file when asked); inspect `git status`/`git log` first — uncommitted changes may be the teammate's, not ours. Treat `opencode.json` (MCP servers: fetch, postgres, docker) as existing config — don't remove or reconfigure it unless asked.

## Backend commands (all run from `backend/`)

```bash
cp .env.example .env        # REQUIRED first — see gotcha below
docker-compose up -d        # PostGIS 16-3.4 container `karwan_e_khizr_db`
uvicorn main:app --reload   # API on /api, healthcheck at unprefixed /health
pytest                      # full suite; baseline ~532 tests (see plan.md)
alembic upgrade head        # 7 migrations currently
```

Gotchas:

- `core/config.py` instantiates `Settings()` **at import time** with required `DATABASE_URL`/`SECRET_KEY` and no defaults — any backend entrypoint fails immediately without `backend/.env`. Test files set env fallbacks themselves (there is no `conftest.py`), so pytest runs without `.env`.
- DB-backed tests connect to the real Dockerized Postgres (rolled-back transactions) and **silently skip** when it's unreachable. A green `pytest` run without the container up is NOT the full suite — start Docker for real coverage.
- Seed demo data: `python scripts/seed_dev_db.py` (`--status`, `--reset` flags documented in `data/README.md`). Default `insert` mode skips existing rows — use `replace` after editing `data/seed_dataset.py` or changes won't take. All seed IDs are deterministic (`uuid.uuid5`), so seeding/reset is repeatable.
- `scripts/import_transit_data.py` loads the canonical dataset `docs/transit_data.json` into the DB; `scripts/verify_graph_buildable.py` is an offline graph smoke test.
- `backend/data/README.md`'s "admin/dev routers not wired in yet" section is stale — both ARE mounted now in `api/router.py`.

## Backend architecture invariants (context — do not duplicate or rework)

- Entrypoint `main.py`: lifespan builds the immutable routing graph once at startup and stores it on `app.state`; bad DB/static data fails startup loudly. The graph is NOT refreshed after later data changes — restart the server or `POST /api/admin/graph/rebuild` (admin role required).
- Layering: `routing/` and `simulation/` have zero FastAPI/SQLAlchemy imports; `api/` is the only layer touching both.
- External systems go through Protocol interfaces: `VehicleLocationProvider`, `WalkingProvider`, `PaymentProvider`.
- ORM models are never returned from endpoints — responses always use API schemas (`api/*/schemas.py`). Those schemas are the single source of truth for the client contract.
- Service functions take `AsyncSession` and flush but never commit; the route handler commits.
- Unauthenticated-by-design surfaces (documented decisions, not oversights): simulation control `/api/transit/realtime/simulation/*` and read-only `/api/dev/*`. `/api/admin/*` is gated with `require_role(ROLE_ADMIN)` at mount time.

## Data reality — never fabricate

No invented coordinates, stop names, timetables, route geometry, endpoints, params, or response fields. Ever. Known gaps (see `docs/DATA_GAPS.md`): most routes have no timetable or geometry; many stops lack coordinates; only FR-01/04/07/14 have verified stop-level timetables. Anything simulated/demo must be labeled as such, never presented as live intelligence.

## Frontend conventions

- Verify every endpoint/response shape against `backend/api/*/schemas.py` (or the running OpenAPI docs) before integrating — known groups live under `/api/transit` (incl. `/journeys`, `/realtime`), `/api/auth`, `/api/users`, `/api/fares`, `/api/tickets`.
- Data flow: `components → hooks/state → services → API`. No component calls `fetch()` or hardcodes backend URLs; realtime goes through a centralized service + hook (e.g. `useRealtimeVehicles()`); polling intervals configurable, not hardcoded.
- Mock/demo data lives in `frontend/mocks/`, matches real API types, is trivially swappable, and is visibly labeled demo data. Handle missing backend data with proper loading/empty states instead of inventing geography.
- Figma is the UI source of truth — implement faithfully, don't redesign. On conflicts (Figma vs backend contract vs this file): state the conflict, preserve API compatibility, ask before breaking changes.
- Journey recommendation logic has a single owner; never duplicate the backend routing engine inside UI components.
- Priorities: P0 = launch, navigation, origin/destination search, journey results + recommendation display, realtime vehicles, Android demo. Auth/ticketing/payments are P2 — don't build ahead of that.
