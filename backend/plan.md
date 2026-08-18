# Karwan-e-Khizr Backend — Phase 2 Implementation Plan

## Execution Order: Phases 1→2→3→4→5→6 (sequential)

---

# SESSION HANDOFF — Phase 1 COMPLETE (2026-08-17, agent handoff)

## Status: Phase 1 (Transit Data Import) is COMPLETE, verified, and committed.

**Test baseline: 431 passed (406 original + 25 new Phase 1 tests), 0 failures.**

## What Is Done (Phase 1, all committed)

### New files
- `seeding/transit_data_importer.py` — dedicated converter from the canonical
  `docs/transit_data.json` shape (uuid `id`s + human `key`s, `operators`,
  `trips` with embedded `stop_times`, top-level `route_stops` that only cover
  red_line) to the generic `ImportDataset`. Direction normalized
  `Forward`/`Backward` → `forward`/`backward`. FR-14's null
  `departure_offset_s` → `departure = arrival`. FR routes get RouteStop rows
  DERIVED from `trips[].stop_times` (sequence = index+1, distance None) since
  their only ordered stop sequence lives there; red_line stops come from the
  top-level array (23 rows). Result: 2 agencies, 122 stops, 26 routes,
  115 route_stops, 4 trip patterns.
- `scripts/import_transit_data.py` — CLI: `--dataset` (default
  `docs/transit_data.json`), `--service-date` (default today), `--dry-run`.
  Uses `allow_routes_without_stops=True`.
- `alembic/versions/a1b2c3d4e5f6_make_stops_location_nullable.py` — makes
  `stops.location` nullable (plan.md section B: ~105 of 122 stops have null
  coords in the canonical dataset).
- `alembic/versions/b2c3d4e5f6a7_add_stops_ref.py` — adds nullable
  `stops.ref` (see the data-integrity bug below).
- `tests/test_transit_data_import.py` — 25 tests: converter mapping, trip
  pattern generation, validation, full DB import (row counts), null vs
  non-null coords, FR-01 offsets, idempotency, deterministic IDs,
  service-date separation, graph skipping unlocated stops, simulator guards.

### Modified files
- `seeding/import_schema.py` — `ImportDataset` extended with `trip_patterns`
  + `trip_stop_times` + `stop_times_for(route_ref, direction)` helper;
  `ImportTripPattern`/`ImportStopTime` dataclasses; `ImportStop` lat/lon now
  `float | None = None`.
- `seeding/parsers.py` — optional generic JSON `trip_patterns` parsing
  (additive; the generic parser still REQUIRES lat/lon for stops — only the
  canonical converter builds null-coord stops directly).
- `seeding/validation.py` — `validate_dataset(dataset, *,
  allow_routes_without_stops=False)` downgrades `insufficient_stops` errors
  to warnings; full trip-pattern validation (refs, direction, headway, count,
  times, stop-time offsets, `trip_count_exceeds_last_trip_start` warning).
- `seeding/importer.py` — `import_dataset(..., allow_routes_without_stops=
  False, service_date=None)`; `generate_trip_starts` (exactly
  `total_trips_per_day`, NOT capped by `last_trip_start`); deterministic
  uuid5 trip/stop_time IDs; replace-semantics re-import; null-coord stops.
- `db/models/stop.py` — `location` nullable + new `ref` column.
- `routing/graph.py` — `_fetch_nodes` filters `Stop.location.is_not(None)`;
  `_fetch_ride_edges` skips pairs whose stops aren't graph nodes.
- `simulation/trip_builder.py` — `load_trip_schedule` returns None if any
  stop lacks coords; `build_trip_for_route` raises ValueError.
- `api/transit/schemas.py` / `api/transit/router.py` — `StopRead.location` is
  `Coordinates | None`; `_stop_read` returns null location for unlocated
  stops.
- `tests/test_transit_models.py` — the one pre-existing test that asserted
  `stops.c.location` NOT nullable was updated to assert nullable (with a
  justification docstring).

## Problems Found & Solved This Session

1. **DATA-INTEGRITY BUG (major): stop name collision.** `docs/transit_data.json`
   contains FOUR pairs of DISTINCT stops that share a display `name`:
   `faizabad`(Red Line, has coords)/`cda_faizabad`(CDA feeder, null coords),
   `bari_imam`/`cda_bari_imam`, `g9_markaz`/`cda_g_9_markaz`,
   `g10_markaz`/`cda_g_10_markaz`. The importer's name-based get-or-create
   collapsed each pair into ONE row (118 stops instead of 122), which would
   corrupt the routing graph (both routes sharing a stop node) AND make
   re-import crash with `MultipleResultsFound`. FIX: added nullable `stops.ref`
   column holding the dataset's stable `key`; `_get_or_create_stop` now
   matches by `ref` first, falling back to `name` only for ref-less
   (legacy/admin) data. Now: 122 stops imported, idempotent re-import works
   (275 replaced / 0 new on second run).
2. **Timezone round-trip bug in deterministic trip IDs.** `trip_id_for` used
   `start.isoformat()` on the PKT-aware insert value; Postgres stores
   TIMESTAMPTZ and asyncpg returns UTC, so the read-back value produced a
   DIFFERENT UUID than the one used at insert time (idempotency and
   determinism broken). FIX: `trip_id_for` normalizes via
   `start.astimezone(PKT)` before hashing. Tests assert on
   `scheduled_start_time.astimezone(PKT)` wall-clock.
3. **Wrong canonical offsets in my first test draft.** I hard-coded plan.md's
   example offsets (130/150) but the real FR-01 dataset is 168/188 — fixed to
   match the canonical data (plan.md's §E example is illustrative, not exact).
4. **Operational gotcha (IMPORTANT for the next agent):** pytest runs against
   the LIVE docker Postgres (rolled-back transactions) and assumes an EMPTY
   baseline (e.g. `test_validate_endpoint_reports_errors_without_persisting`
   expects `stops_total == 0`). If you run `scripts/import_transit_data.py`
   (which COMMITS), you MUST delete rows from
   `stop_times → trips → route_stops → routes → stops → agencies` (in that
   order, or cascade) before running pytest, or ~10 tests fail.

## Verified End-to-End
`python scripts/import_transit_data.py --service-date 2026-08-16`:
- agencies 2, stops 122, routes 26, route_stops 115, trips 275, stop_times 6242
- second run: trips replaced=275, created=0 (idempotent), static 0 created
- graph builds: 17 nodes (located stops only), 6 ride_edges, 2 walk_edges
- DB was cleaned back to empty baseline after verification.

## What Remains

### Next move (Phase 2 — Geospatial Enrichment), see §C / §M-Phase 2
1. `db/models/stop.py` — add `coordinate_source`, `coordinate_confidence`
   columns; migration `xxxx_add_stop_coordinate_provenance.py`.
2. `seeding/geocoding.py` — Nominatim geocoding service (httpx, already in
   requirements). Bounding box 33.5–33.85N, 73.0–73.3E. Max 1 req/sec.
   Only fill NULL coords; never overwrite APPROXIMATE seed coords.
3. `scripts/geocode_stops.py` — CLI (network access required; ~105 stops).
4. `tests/test_geocoding.py` (mocked Nominatim).
5. Update `docs/DATA_GAPS.md`/`SOURCES.md` with enrichment results.

### Later phases (see §M)
- **Phase 3** Route geometry via OSRM → `Route.path` + `geometry_source`/
  `geometry_confidence` columns; `GET /api/transit/routes/{id}/geometry`.
- **Phase 4** Enhanced realtime API (bearing, stop names, ETA, delay);
  `GET /api/transit/realtime/vehicles/{id}/eta`.
- **Phase 5** `POST /api/admin/trips/generate` daily-trip endpoint.
- **Phase 6** Frontend contract finalization (route geometry in journey legs,
  CORS, documented response shapes).

### Known open items / thinking
- `Stop` model still has NO uniqueness constraint on `ref` (deliberate: seed
  rows predate it). If Phase 2 wants to enforce uniqueness, add a partial
  unique index WHERE ref IS NOT NULL — but only if a bug demands it.
- RouteStop `distance_along_route_m` still NULL everywhere (Phase 3 fills it).
- `Route.path` still NULL everywhere (Phase 3 fills it).
- Generic parser still requires stop lat/lon — by design (existing tests
  depend on `test_parse_json_dataset_rejects_missing_required_field`).
- The 21 routes with no stop sequence at all import fine via
  `allow_routes_without_stops=True` (warning, not error). If we later get
  stop sequences for them, just add to transit_data.json and re-import.
- FR-01's documented 16th trip starts 22:15 but `last_trip_start` says 22:00.
  We generate the documented 16 trips and surface the mismatch as a
  validation warning (`trip_count_exceeds_last_trip_start`). Do NOT silently
  drop the trip.

## Active Todo List (for next agent)
- [x] Phase 1 import pipeline (schema/parser/validation/importer) + scripts
- [x] Phase 1 migration(s): stops.location nullable, stops.ref
- [x] Phase 1 test file `tests/test_transit_data_import.py` (25 tests)
- [x] Full suite green: 431 passed / 0 failed
- [x] Phase 2: geocoding service + script + provenance columns + tests
- [x] Phase 2 follow-up: live geocoding run against Nominatim (71/105 resolved,
      34 UNKNOWN, DATA_GAPS.md §7.1 and SOURCES.md §6 updated)
- [ ] Phase 3: OSRM route geometry + provenance + geometry API + tests
- [ ] Phase 4: enhanced realtime API (bearing/ETA/delay) + tests
- [ ] Phase 5: admin daily-trip generation endpoint + tests
- [ ] Phase 6: frontend API contract finalization + tests
- [ ] Remember: clean transit tables before pytest after running import script

---

# SESSION HANDOFF — Phase 2 COMPLETE (2026-08-17, agent handoff)

## Status: Phase 2 (Geospatial Enrichment) is fully complete, including live
## geocoding against Nominatim. 88 of 122 stops now have coordinates.

**Test baseline: 447 passed (431 Phase-1 baseline + 16 new Phase 2 tests), 0
failures.**

## What Is Done (Phase 2, all committed)

### New files
- `seeding/geocoding.py` — `Geocoder` Protocol (same shape as
  `ticketing.payments.provider.PaymentProvider`) + `NominatimGeocoder`, the
  real implementation wrapping OpenStreetMap's public Nominatim `/search`
  endpoint. Enforces Nominatim's usage policy (max 1 req/sec, descriptive
  `User-Agent`, sequential-only). `in_bounding_box()` validates every
  candidate against the Islamabad/Rawalpindi box (33.5-33.85N, 73.0-73.3E)
  from plan.md section C - a candidate outside it is rejected, never
  accepted as a fallback. `query_variants()`/`geocode_stop_name()` try
  "`<name>, Islamabad, Pakistan`" then "`<name>, Rawalpindi, Pakistan`" in
  order. Never fabricates a coordinate: no in-bounds candidate -> `None`.
- `scripts/geocode_stops.py` — CLI: `--dry-run` (look up matches, write
  nothing), `--limit N` (process only the first N null-coordinate stops, by
  name - useful for a smoke test once network access exists). Core logic
  (`geocode_null_coordinate_stops`) takes a plain `AsyncSession` + `Geocoder`
  so tests can inject a rolled-back session and a fake geocoder with zero
  real network/database-commit side effects. Only ever queries
  `Stop.location IS NULL` rows; on a match sets `location` +
  `coordinate_source="NOMINATIM"` + `coordinate_confidence="APPROXIMATE"`;
  on no match, leaves `location` NULL and sets
  `coordinate_confidence="UNKNOWN"` (`coordinate_source` stays NULL - nothing
  was actually sourced).
- `alembic/versions/c3d4e5f6a7b8_add_stop_coordinate_provenance.py` — adds
  nullable `stops.coordinate_source` (String(50)) and
  `stops.coordinate_confidence` (String(20)), chained on `b2c3d4e5f6a7`
  (Phase 1's last migration).
- `tests/test_geocoding.py` — 16 tests in three layers: (1) pure
  `seeding.geocoding` logic against `httpx.MockTransport` - no real network,
  matching plan.md section L's "mocked Nominatim responses" - covering
  bounding-box accept/reject, query fallback, HTTP-error -> `GeocodingError`,
  and the 1-req/sec throttle actually elapsing; (2) import-time provenance
  (real DB, rolled back) - a stop imported WITH coordinates gets
  `coordinate_source="SEED_DATUM"` + the dataset's own confidence, a stop
  imported WITHOUT coordinates gets no provenance yet; (3)
  `geocode_null_coordinate_stops` against a fake `Geocoder` (real DB, no
  real network) - only null-location stops are queried/updated, located
  stops are never even queried, dry-run writes nothing, limit is respected.

### Modified files
- `db/models/stop.py` — added `coordinate_source: Mapped[str | None]`
  (String(50)) and `coordinate_confidence: Mapped[str | None]` (String(20)),
  both nullable, with the value-set docstring from plan.md section C.
- `seeding/import_schema.py` — `ImportStop` gained
  `confidence: str | None = None`, carrying a source dataset's own
  per-stop confidence rating through to the importer (doc comment
  explains this is copied onto `Stop.coordinate_source`/
  `coordinate_confidence` only for stops that already have a location).
- `seeding/transit_data_importer.py` — `transit_data_to_dataset` now passes
  `confidence=stop.get("confidence")` into each `ImportStop` (module
  docstring's stops-mapping bullet updated to match).
- `seeding/importer.py` — `_get_or_create_stop` gained a `confidence`
  parameter; when CREATING a new stop (never on update/move), if the stop
  has a location it's tagged `coordinate_source="SEED_DATUM"` +
  `coordinate_confidence=confidence`; if it has no location, both stay
  `None` (left for `seeding.geocoding` to fill in later). Single call site
  in `import_dataset` updated to pass `import_stop.confidence` through.

## Design decision worth flagging for the next agent

plan.md section C's wording for `coordinate_confidence` ("carried from
transit_data.json's confidence field, or set during enrichment") is
slightly ambiguous about whether the JSON's per-stop `confidence` value
(which every stop has, located or not - see `docs/transit_data.json`)
should be copied onto `coordinate_confidence` even for NULL-coordinate
stops. **I chose NOT to do that**: `coordinate_confidence` is only set at
import time for stops that already have a location (mirroring
`coordinate_source`, which obviously can't be `"SEED_DATUM"` for a stop
with no coordinate at all). A null-coordinate stop gets no provenance
until `scripts/geocode_stops.py` actually resolves (or fails to resolve)
it. Rationale: `coordinate_confidence` is documented as being about trust
in the *coordinate specifically* ("how much to trust `location`"), and a
stop with `location IS NULL` has no coordinate to rate yet - carrying over
the JSON's identity/naming confidence (e.g. "RECONSTRUCTED" for a stop
whose *name* came from a secondary source) onto a coordinate field would
conflate two different kinds of confidence. If a future agent disagrees,
this is a one-line change in `seeding/importer.py`'s `_get_or_create_stop`.

## Live geocoding run completed (2026-08-17)

Ran `python scripts/geocode_stops.py` against the live imported dataset (122
stops, 105 with null coordinates). Results:

- **71 stops resolved** — `coordinate_source="NOMINATIM"`,
  `coordinate_confidence="APPROXIMATE"`. All within bounding box.
- **34 stops unresolved** — `coordinate_confidence="UNKNOWN"`, location left
  NULL. Mostly informal/colloquial stop names not in OSM ("Bar Council",
  "College Morh", "Metro CNG", "Abpara Market", etc.).
- **17 SEED_DATUM stops** — unchanged, coordinates untouched.
- **Total: 88 of 122 stops now have coordinates (72%).**
- Two display-name mismatches noted: "6th Road" → "Korang Town Road",
  "Metropolitan Corporation" → "Street #15" — acceptable ambiguity.

Graph builds with 88 nodes (up from 17). The 34 unresolved stops are
skipped by graph construction and the simulator.

DATA_GAPS.md §7.1 and SOURCES.md §6 have been updated with actual results.

## Verified this session
- `python scripts/import_transit_data.py --service-date 2026-08-16`:
  agencies 2, stops 122 (17 `SEED_DATUM`/`APPROXIMATE`), routes 26,
  route_stops 115, trips 275, stop_times 6242.
- `alembic upgrade head` applies `c3d4e5f6a7b8` cleanly.
- Full suite: 447 passed, 0 failed.
- `python scripts/geocode_stops.py --dry-run`: 71 geocoded, 34 unresolved.
- `python scripts/geocode_stops.py` (live): same results as dry-run.
- DB cleaned back to empty baseline after verification.
- Full pytest suite run post-clean: 447 passed, 0 failed.

## What Remains

### Next move (Phase 3 — Route Geometry via OSRM), see §D / §M-Phase 3
1. `db/models/route.py` — add `geometry_source`, `geometry_confidence`
   columns; migration `xxxx_add_route_geometry_provenance.py`.
2. `seeding/route_geometry.py` — OSRM road-snapping service (httpx, already
   in requirements). Public demo server `https://router.project-osrm.org`
   for now; same network-access caveat as Phase 2 applies in this sandbox.
3. `scripts/generate_route_geometry.py` — CLI.
4. `api/transit/router.py` / `schemas.py` — expose `Route.path` as GeoJSON;
   new `GET /api/transit/routes/{id}/geometry` endpoint.
5. `tests/test_route_geometry.py` (mocked OSRM responses, same pattern as
   `tests/test_geocoding.py`'s `httpx.MockTransport` usage).
6. Only routes whose stops ALL have coordinates can get geometry - which
   depends on Phase 2's geocoding run having actually happened first (or on
   routes that only use the 17 already-located seed stops). Check
   `coordinate_source IS NOT NULL` coverage per route before assuming a
   route is geometry-eligible.

---

# SESSION HANDOFF — Phase 3 COMPLETE (2026-08-17, agent handoff)

## Status: Phase 3 (Route Geometry via OSRM) is code-complete. Live OSRM
## generation WAS run and verified on 2026-08-17 (verification/integration agent)
## — see the "Verification Agent Handoff" section below. The mechanism works
## end-to-end against real OSRM + PostGIS, but generated geometry for ZERO real
## routes: after Phase 2's geocoding, no route's full ordered stop sequence is
## located, and the script correctly never fabricates a line for an unlocated stop.

**Test baseline this session: 8 new pure tests passed + 9 new DB-backed
tests correctly SKIPPED (no live Postgres reachable here). Full suite:
220 passed, 242 skipped, 2 pre-existing DB-connection failures unrelated
to this change (same 2 fail identically on the pre-Phase-3 tree - they
require a live DB this sandbox doesn't have). 464 tests collected total
(447 Phase-2 baseline + 17 new Phase 3 tests).**

## What Is Done (Phase 3, all in this session's tree — not yet run live)

### New files
- `seeding/route_geometry.py` — `RouteGeometryProvider` Protocol (same
  shape as `seeding.geocoding.Geocoder`) + `OSRMRouteGeometryProvider`,
  wrapping OSRM's public demo server's `route` service (`driving`
  profile, `overview=full&geometries=geojson`) via the *plain* `route`
  endpoint (not `trip`/TSP) so waypoints are never reordered — a transit
  route's stop sequence is fixed. `RouteGeometryResult` carries
  `coordinates` (GeoJSON/WKT `(lon, lat)` order — the one place in this
  codebase that's `(lon, lat)` instead of the usual `(lat, lon)`, called
  out explicitly in the docstring) and `leg_distances_m` (one per
  consecutive waypoint pair, from OSRM's own per-leg road distance, not
  Haversine). `cumulative_distances_m()` turns leg distances into
  per-stop `distance_along_route_m` values (starts at 0.0, one more entry
  than legs). `linestring_wkt()` builds the `SRID=4326;LINESTRING(...)`
  string assigned directly to `Route.path`, mirroring how
  `seeding.importer` already assigns `Stop.location` as a WKT string.
  Never fabricates: a route OSRM can't connect raises `RouteGeometryError`
  rather than returning a straight-line/guessed polyline.
- `scripts/generate_route_geometry.py` — CLI: `--dry-run`, `--limit N`.
  Core logic `generate_route_geometry(session, provider, *, dry_run,
  limit)` takes a plain `AsyncSession` + `RouteGeometryProvider` (same
  test-injection pattern as `scripts.geocode_stops
  .geocode_null_coordinate_stops`). `_eligible_routes()` finds every
  Route with >=2 `RouteStop`s where **every** stop in the sequence has a
  non-null `location` (extracted via `ST_X`/`ST_Y`, same pattern as
  `api/transit/router.py`); a route with even one unlocated stop is
  skipped entirely — untouched, not marked UNKNOWN, since it was never
  actually attempted. On success: `Route.path` = WKT LineString,
  `geometry_source="OSRM"`, `geometry_confidence="OSM-DERIVED"`, and each
  `RouteStop.distance_along_route_m` is overwritten from the cumulative
  OSRM leg distances. On OSRM failure for an eligible route:
  `geometry_confidence="UNKNOWN"`, `path`/`geometry_source` left
  untouched (nothing was actually sourced — same asymmetry as
  `geocode_stops.py`'s handling of `coordinate_source` on a failed
  geocode).
- `alembic/versions/d4e5f6a7b8c9_add_route_geometry_provenance.py` — adds
  nullable `routes.geometry_source` (String(50)) and
  `routes.geometry_confidence` (String(20)), chained on `c3d4e5f6a7b8`
  (Phase 2's head).
- `tests/test_route_geometry.py` — 17 tests in three layers (mirrors
  `tests/test_geocoding.py`'s structure exactly): (1) pure
  `linestring_wkt`/`cumulative_distances_m` + `OSRMRouteGeometryProvider`
  against `httpx.MockTransport` — 8 tests, all passing in this sandbox
  with no network; (2) `generate_route_geometry` against a fake
  `RouteGeometryProvider` (real DB, no real network) — eligibility
  (>=2 stops all located; single-stop and unlocated-stop routes both
  skip with `eligible` not incremented), success path (path/provenance/
  distance-per-stop all correct), failure path (`UNKNOWN`, nothing else
  touched), `--dry-run`, `--limit` — 6 tests; (3) API —
  `GET /transit/routes/{id}` embeds a null geometry before generation,
  `GET /transit/routes/{id}/geometry` returns the generated GeoJSON
  LineString after it, both endpoints agree, 404 for a missing route — 3
  tests. All 9 DB-backed tests SKIP (not fail) in this sandbox, same
  convention as every other DB-backed test file.

### Modified files
- `db/models/route.py` — added `geometry_source`/`geometry_confidence`
  columns, same shape/docstring convention as `Stop.coordinate_source`/
  `coordinate_confidence`.
- `api/transit/schemas.py` — new `RouteGeometryRead` (GeoJSON-shaped:
  `type`, `coordinates` as `list[tuple[float, float]] | None`,
  `geometry_source`, `geometry_confidence` — explicitly all-null before
  generation, not an error/omitted field); `RouteDetail` gained a
  required `geometry: RouteGeometryRead` field.
- `api/transit/router.py` — module docstring's "`Route.path` is
  intentionally NOT serialized" paragraph is now the opposite (it IS,
  as of Phase 3) — updated in place. New `_route_geometry_json_expr()`
  (`ST_AsGeoJSON(cast(Route.path, Geometry))`, same extraction pattern as
  the existing lat/lng helpers) and `_route_geometry_read()` builder.
  `get_route` now also selects that expression and populates
  `RouteDetail.geometry`. New endpoint `GET /transit/routes/{route_id}/
  geometry` returning just `RouteGeometryRead` (404 if the route doesn't
  exist), for a client that only needs to redraw the polyline.

## Why nothing was run live this session

This sandbox has **no live PostgreSQL** (no `docker`, no reachable
`localhost:5432`) and **no outbound network access to
`router.project-osrm.org`** (egress here is allow-listed to package
registries only — see the environment's own network-configuration note,
same restriction Phase 2's live-geocoding run explicitly worked around by
running from a different environment). Everything that COULD be verified
without those was: `python -m py_compile` on every new/changed file,
`pytest --collect-only` (464 tests collect with zero import errors), the
full suite run (220 passed / 242 skipped / 2 pre-existing unrelated DB
-connection failures, identical failure signature before and after this
change), and all 8 pure (mocked-HTTP) `test_route_geometry.py` tests
passing outright.

## What Remains

### DONE — run this live, from an environment with DB + `router.project-osrm.org` access
(executed 2026-08-17 by the verification/integration agent; see the next
section for the full write-up):

```
alembic upgrade head          # applies d4e5f6a7b8c9
python scripts/import_transit_data.py --service-date <today>
python scripts/geocode_stops.py                 # if not already run for this DB
python scripts/generate_route_geometry.py --dry-run   # sanity check first
python scripts/generate_route_geometry.py              # live
```

The dry-run and live runs both reported **0 eligible routes** — the
correct, honest outcome given that no route's full stop sequence is
located (Red Line is 1 stop short; FR-01/04/07/14 are 10/4/9/10 short).
The OSRM provider and persistence pipeline were verified end-to-end on a
throwaway two-stop route built from real located stops (geometry generated,
stored to PostGIS, provenance + per-stop distances correct, idempotent,
dry-run writes nothing, limit works) and the throwaway route was deleted
afterward. The database was cleaned back to the empty pytest baseline
after verification.

### Later phases (see §M, unchanged)
- **Phase 4** Enhanced realtime API (bearing, stop names, ETA, delay) +
  optional `Route.path` interpolation in `simulation/engine.py`.
- **Phase 5** `POST /api/admin/trips/generate` daily-trip endpoint.
- **Phase 6** Frontend contract finalization (route geometry in journey
  legs — `RouteGeometryRead` is already in the right shape for this to
  reuse directly, not a new schema — CORS, documented response shapes).

### Known open items / thinking
- `generate_route_geometry`'s `--limit` semantics match `geocode_stops
  .py`'s: "the first N *eligible* candidates" (ordered by `short_name`),
  not "the first N routes overall" — a route skipped for having an
  unlocated stop doesn't count against the limit.
- Re-running `generate_route_geometry.py` on a route that already has
  OSRM-derived geometry **overwrites** it unconditionally (no "don't
  touch existing geometry" guard, unlike `geocode_stops.py`'s stop
  coordinates). This is deliberate: unlike a stop's SEED_DATUM coordinate
  (a real, curated fact worth protecting), OSRM geometry is fully
  re-derivable from the same inputs every time — there is no
  higher-trust source to accidentally clobber yet. If `geometry_source`
  is ever `"MANUAL_VERIFIED"` (not produced by any code today), a future
  agent should add the same protect-existing-higher-trust-source guard
  `_get_or_create_stop` has for `SEED_DATUM`.
- `RouteStop.distance_along_route_m` is silently overwritten by a
  successful geometry generation, even if some other process had set it
  before. There's no plan.md guidance either way here; treated the same
  as `Route.path` itself (OSRM is the single source of truth for both,
  together, in one atomic pass) rather than protecting one field but not
  the other from the same regeneration.

## Active Todo List (for next agent)
- [x] Phase 1 import pipeline + migrations + tests (431 passed)
- [x] Phase 2 geocoding service + script + provenance + tests + live run
      (447 passed, 88/122 stops located)
- [x] Phase 3 OSRM route geometry service + script + provenance columns +
      API exposure + tests (464 tests collect; 8 new pure + 9 new DB tests
      all pass against live PostGIS)
- [x] Phase 3 follow-up: live OSRM generation run completed 2026-08-17 —
      `alembic upgrade head` + import + geocode + geometry script all run
      against real Docker PostGIS; OSRM reached and pipeline verified
      end-to-end on a throwaway 2-stop route; **0 real routes eligible**
      (no route fully located); handoff + docs updated with actual results
- [ ] Phase 4: enhanced realtime API (bearing/ETA/delay) + optional
      `Route.path` interpolation in `simulation/engine.py` + tests
- [ ] Phase 5: admin daily-trip generation endpoint + tests
- [ ] Phase 6: frontend API contract finalization + tests
- [ ] Remember: clean transit tables before pytest after running any
      import/enrichment script that commits

---

# SESSION HANDOFF — Phase 3 VERIFICATION/INTEGRATION COMPLETE (2026-08-17, verification agent)

## Status: Phase 3 verified and stabilized against a live Docker PostgreSQL/PostGIS
## + real OSRM. **464 tests pass (447 Phase-2 baseline + 17 Phase 3), 0 failures,
## 0 skips.** One genuine test bug fixed (see below).

## Live-data verification performed

1. **Environment**: Docker Desktop running; `backend/docker-compose.yml` PostGIS
   16-3.4 container started; DB was empty (alembic at `c3d4e5f6a7b8`).
2. **Migration**: `alembic upgrade head` applied `d4e5f6a7b8c9` cleanly; exactly one
   head (`d4e5f6a7b8c9`); `downgrade -1` then `upgrade head` round-trip verified.
3. **Import** (`scripts/import_transit_data.py --service-date 2026-08-17`): 2 agencies,
   122 stops, 26 routes, 115 route_stops, 275 trips, 6242 stop_times. 17 stops had
   SEED_DATUM coordinates.
4. **Geocoding** (`scripts/geocode_stops.py`, live Nominatim): 71 of 105 null-coord
   stops resolved (NOMINATIM/APPROXIMATE), 34 UNKNOWN — **identical result to Phase 2's
   documented live run**. Total 88/122 located.
5. **Geometry generation** (`scripts/generate_route_geometry.py`, live OSRM):
   - `--dry-run` and the live run both reported **0 eligible routes**. Verified directly
     in the DB why: NO route has its full ordered stop sequence located — Red Line 22/23
     (only `Peshawar Morr (Interchange)` missing, genuinely UNKNOWN after geocoding),
     FR-01 16/26, FR-04 21/25, FR-07 14/23, FR-14 8/18. The script's "skip a route with
     even one unlocated stop" rule is exactly why 0 is correct — it never fabricates.
   - **End-to-end mechanism verified** using a throwaway 2-stop route built from two
     real SEED_DATUM stops (`Ammar Chowk`, `Bank Road`): real OSRM reached, valid
     GeoJSON LineString returned (82 points), PostGIS accepted it, `ST_Length` ~2.6 km,
     waypoints in order, `geometry_source="OSRM"`/`geometry_confidence="OSM-DERIVED"`
     persisted, `RouteStop.distance_along_route_m` = (0.0, 2612.1), re-run idempotent,
     `--dry-run` wrote nothing, `--limit 1` respected. Throwaway route deleted
     afterward; DB restored to the 26-route imported baseline, then cleaned to the empty
     pytest baseline.
6. **API**: Phase 3 tests cover `GET /transit/routes/{id}` embedded geometry (null
   before generation, GeoJSON after) and `GET /transit/routes/{id}/geometry`, plus 404 —
   all pass.

## Genuine bug found and fixed

- `tests/test_route_geometry.py::test_generate_route_geometry_respects_limit` created
  3 routes under the **same** agency name, violating `agencies.name` unique constraint
  → `IntegrityError` against real PostGIS. It had never actually run (the original
  Phase 3 sandbox could only skip DB tests). Fixed by giving each of the 3 iterations
  its own agency name. This is the only code change the verification agent made beyond
  docs/handoff.

## Non-bugs confirmed as correct behavior (not "failures")

- 0 eligible real routes is the intended, honest outcome (see above), not a bug.
- Docs originally said "live run has not happened" — those passages were updated with
  the actual live results (DATA_GAPS.md §6, MAP_AND_REALTIME_RECOMMENDATIONS.md,
  SIMULATION_DATA_SPEC.md, TRANSIT_RESEARCH.md §9/§16, SOURCES.md §4a).
- `--limit` counts eligible candidates only (matches `geocode_stops.py` convention).
- OSRM geometry is road-snapped (`OSM-DERIVED`), never claimed to be the BRT's real
  alignment; docs preserve that distinction throughout.

## What remains before Phase 4

- Nothing blocks Phase 4. Phase 3's geometry generation is code-complete, live-verified,
  and the DB is back at the empty pytest baseline. When any route's full stop sequence
  becomes located (e.g. manually resolving `Peshawar Morr (Interchange)` or the ~34
  UNKNOWN stops), `python scripts/generate_route_geometry.py` will populate `Route.path`
  for it. `simulation.engine` polyline interpolation remains Phase 4 work.

---

# SESSION HANDOFF — Phase 4 COMPLETE, NOT YET LIVE-VERIFIED (2026-08-17, agent handoff)

## Status: Phase 4 (Enhanced Realtime API) is code-complete and passing in a sandbox
## with no Docker/no live Windows environment. **This has NOT been verified against a
## real Docker Postgres/PostGIS environment by this agent** - that verification is
## expected to happen next, by OpenCode, the same way it verified Phase 3.

**Test baseline this session: 500 passed, 0 failed, 0 skipped, in a manually-installed
(non-Docker) Postgres 16 + PostGIS sandbox** (464 Phase-3-verified baseline + 36 new
Phase 4 tests). No skips this session because this sandbox DOES have a real, reachable
Postgres (unlike the original Phase 3 authoring session) - unlike route geometry, Phase
4 needed no external network service (no Nominatim, no OSRM), so there was nothing this
sandbox categorically couldn't reach. The one thing still unverified is whether these
same 36 tests pass identically against the actual Docker Postgres/PostGIS environment
OpenCode used for Phase 1-3 - there is no specific reason to expect a difference (same
PostGIS version family, same SQL), but it has not been checked directly.

## What Is Done (Phase 4, all in this session's tree)

**Database changes: none** (plan.md section M confirms Phase 4 needs none - correct,
verified: no new migration was added or needed).

### New files
- `api/transit/realtime/eta_router.py` — `GET /transit/realtime/vehicles/{vehicle_id}/eta`
  (plan.md section G/H/I). Kept as its own router (not folded into `router.py`) purely
  to match the file plan.md's Phase 4 list names. Returns every `StopTime` on the
  vehicle's current trip with `sequence >=` the sequence of `next_stop_id` (or
  `current_stop_id` for the single-stop-schedule edge case where there's no next stop
  but the trip also isn't `completed`); `etas: []` once `status == "completed"` - not
  an error. `404` under the same condition as `GET /vehicles/{vehicle_id}` (no active
  position). `estimated_arrival` always equals `scheduled_arrival` and
  `delay_seconds` is always `0.0` (plan.md section I: a simulated vehicle IS the
  schedule, no independent "actual" position exists to diverge from it).
- `tests/test_engine_geometry_interpolation.py` — 12 pure tests (no DB) for
  `simulation.geo.point_along_polyline` and `compute_position_at`'s new
  `route_geometry` parameter: following a bend vs. a straight chord, bearing matching
  the local polyline segment (not the overall stop-to-stop bearing), clamping,
  `route_geometry=None` reproducing pre-Phase-4 behavior byte-for-byte (the explicit
  regression guard for "additive, not a replacement"), and falling back to
  straight-line when the supplied geometry doesn't actually cover the stop pair in
  order (never fabricates a wrong-direction position).
- `tests/test_enhanced_realtime.py` — 13 DB-backed tests against the REAL `main.app`
  (unlike the older `tests/test_realtime_api.py`, which builds its own isolated mini
  app) with `get_session` overridden - this also proves `eta_router`/`router.py` are
  correctly mounted via `api/router.py`, not just that the underlying functions work.
  Covers: route/stop name resolution, bearing on a known-direction route, speed
  non-negativity, delay always exactly `0.0` when a next stop exists, all
  next-stop/ETA/delay/bearing fields `None` together for a `completed` trip, a
  route WITH real `Route.path` geometry set directly in the DB actually changing the
  reported bearing (proves `simulation.provider._load_route_geometry` wiring works,
  not just the pure engine math), a route with NO geometry (today's universal real
  case) behaving exactly as before, and the new ETA endpoint's 404/ordering/
  completed-trip-is-empty/scheduled-arrival-cross-check behavior.

### Modified files
- `simulation/geo.py` — added `compute_bearing` (great-circle initial bearing,
  degrees, normalized `[0, 360)`) and `point_along_polyline` (snap-`start`/`end` to
  their nearest polyline vertex by straight-line distance, then interpolate by arc
  length between those two vertices - **documented simplification**: nearest-VERTEX,
  not nearest-point-on-segment, acceptable at OSRM's typical vertex density, same
  spirit as this file's pre-existing `interpolate_point` simplification). Returns
  `None` (never fabricates) when `end`'s nearest vertex isn't strictly after
  `start`'s, or when both snap to the same vertex.
- `simulation/engine.py` — `SimulatedPosition` gained `bearing: float | None` and
  `speed_kmh: float | None`. `compute_position_at` gained an optional
  `route_geometry: list[Point] | None = None` parameter (plan.md's own pseudocode
  used `list[tuple[float,float]]`; used the more specific `Point` - a `NamedTuple`
  subclass of `tuple[float,float]`, so still satisfies that shape - for consistency
  with every other `simulation.*` signature). Bearing: `None` whenever
  `next_stop_id is None` (case 2 `completed`, or a degenerate single-stop schedule in
  case 1); cases 1/3 (stationary) use a straight current-to-next-stop bearing; case 4
  (`en_route`) uses `point_along_polyline`-derived bearing when `route_geometry`
  actually covers the segment, else falls back to the same straight bearing. Speed:
  `0.0` whenever stationary (cases 1-3); in case 4, the CONSTANT implied speed of the
  whole current inter-stop segment (straight-line/haversine distance ÷ segment
  duration) - deliberately NOT recomputed from the road-following distance even when
  `route_geometry` is used for position/bearing, because
  `simulation.timing.compute_stop_time_offsets` already derived that segment's
  duration from the SAME straight-line distance assumption (see that module's
  docstring) - reporting a longer road-distance-based speed here would be
  inconsistent with the schedule the position itself is honoring, not more accurate.
  `route_geometry=None` (the default) reproduces every byte of pre-Phase-4 behavior -
  regression-tested explicitly in `tests/test_engine_geometry_interpolation.py`.
- `simulation/provider.py` — new `_load_route_geometry(session, route_id)` loads
  `Route.path` via `ST_AsGeoJSON` (same extraction pattern `api/transit/router.py`
  and `simulation/trip_builder.py` already use for the identical GeoAlchemy2-WKB
  problem) and converts GeoJSON's `[longitude, latitude]` pairs to
  `simulation.geo.Point`'s `(latitude, longitude)` order right at this DB-facing
  boundary - documented explicitly so every other file under `simulation/` can stay
  `(lat, lon)`-only throughout, matching `Point`'s own convention, with the one
  GeoJSON `(lon, lat)` quirk contained to this one function (mirrors how Phase 3's
  handoff called out the same quirk for `seeding.route_geometry`).
  `SimulatedVehicleLocationProvider._position_for_trip` now calls it per trip and
  passes the result through to `compute_position_at`. Since Phase 3 verified 0 real
  routes currently have geometry, this returns `None` for essentially every real trip
  today - inert in production data, but wired correctly (see
  `tests/test_enhanced_realtime.py`'s DB-level geometry test, which sets `Route.path`
  directly to prove the wiring rather than waiting for real data to exist).
- `api/transit/realtime/schemas.py` — `VehiclePositionRead` extended with
  `route_short_name`, `route_color`, `bearing`, `speed_kmh`, `current_stop_name`,
  `next_stop_name`, `scheduled_arrival_next_stop`, `estimated_arrival_next_stop`,
  `delay_seconds` (all optional/nullable, matching plan.md section G's example
  response shape exactly) - purely additive, no existing field removed or retyped.
  New `ETARead`/`VehicleETAList`.
- `api/transit/realtime/router.py` — every handler now also takes
  `session: AsyncSession = Depends(get_session)` (same dependency
  `api/transit/router.py` already uses) purely to batch-resolve the new display
  fields a bare `SimulatedPosition` doesn't carry - stop names, route short_name/
  color, and each active trip's next-stop `StopTime.arrival_offset_s`. Exactly 3
  extra queries total per request (stop names, route info, StopTime offsets), never
  N+1 - same batching discipline `api/transit/router.py`'s route-detail endpoint
  already follows. Deliberately did NOT push this into the `VehicleLocationProvider`
  Protocol (documented explicitly in the module docstring): a position's identity
  (where/status/bearing/speed) is the provider's job and must stay swappable for a
  future real-GPS provider (plan.md section J); resolving how a UUID displays is an
  ordinary API-presentation concern this router already owned for other reasons.
  `scheduled_arrival_next_stop` is derived from `position.as_of - elapsed_s`
  (`== Trip.scheduled_start_time`) plus the next stop's `arrival_offset_s` - no
  second `Trip` query needed, since `SimulatedPosition` already carries everything
  required to reconstruct it.
- `api/router.py` / `api/transit/realtime/__init__.py` — wired `realtime_eta_router`
  in alongside `realtime_router`/`vehicles_router` (both already always-safe-to-mount,
  same category); updated the module docstring's integration-note code sample to
  match.
- `tests/test_simulation_engine.py` — added `bearing`/`speed_kmh` assertions to the
  existing fixtures (not-started/at-stop/en-route/completed/single-stop cases) plus
  standalone `compute_bearing` unit tests (north/east/south/west/degenerate-identical
  -points cases).

## Design decisions worth flagging for the next agent

1. **Where "compute bearing" lives.** plan.md's Phase 4 file list attributes bearing
   to BOTH `engine.py` ("Add bearing computation") and `router.py` ("Compute
   bearing, load stop names"), which read as possibly overlapping. Read this as
   `engine.py` owning the actual geometry math (kept there deliberately - it's a
   pure, DB-free computation the existing architecture already isolates in exactly
   that module) and `router.py` only surfacing the value the engine already
   computed, alongside the display-name lookups it was already going to need. If a
   future agent disagrees and wants `router.py` to independently recompute/override
   bearing, that would duplicate `simulation.geo.compute_bearing` for no clear
   benefit - flagging so it's a deliberate choice to revisit, not an oversight.
2. **`speed_kmh` uses the straight-line segment distance, never the road-following
   one**, even when `route_geometry` is present and used for position/bearing - see
   `simulation/engine.py`'s modified docstring for the full reasoning (in short:
   `compute_stop_time_offsets` already fixed this segment's DURATION using the
   straight-line/`distance_along_route_m` assumption; recomputing speed from a
   longer road distance over that same fixed duration would just be a different,
   inconsistent number, not a more accurate one).
3. **`api/router.py` was modified**, even though earlier phases' handoffs describe it
   as belonging to "whoever reconciles the three workstreams" / out of a single
   workstream's ownership bounds. Necessary here because Phase 4 explicitly adds a
   new endpoint (`GET /vehicles/{id}/eta`) that has to actually be reachable to
   satisfy the phase's stated goal - an unmounted router isn't a completed feature.
   Kept the change minimal (three lines: one import, one `include_router` call) and
   updated the two docstrings (`api/router.py`'s own comment,
   `api/transit/realtime/__init__.py`'s integration note) that referenced the old
   two-router state, so they don't go stale.
4. **Did not touch `simulation/timing.py`** - plan.md section F explicitly says "No
   changes for routes with real timetable data... `compute_stop_time_offsets()`
   remains available for demo-trip creation," and nothing in Phase 4's actual file
   list or goal required a change there. Confirmed by reading it fully before
   deciding not to touch it, not by assumption.
5. **Nothing in `docs/*.md` was updated this session** - Phase 4 adds no new external
   dependency, no new data-quality finding, and no change to what's geocoded/
   geometry-generated; there was nothing accurate to add to `DATA_GAPS.md`/
   `SOURCES.md` that Phase 2/3's entries don't already cover. Flagging the absence
   explicitly so it reads as a decision, not an omission.

## Why this could not be live-verified against Docker this session

This agent's sandbox has no Docker and no ability to reach a Windows host - same
categorical limitation every prior authoring-agent session in this plan.md has noted
(Phase 3's authoring session, Phase 2's live-geocoding gap, etc.). What COULD be done
without Docker WAS done, and unlike Phase 2/3, that turned out to be everything Phase
4 needs, because Phase 4 requires no external network service (no Nominatim, no OSRM)
and no schema change - the only new failure mode Docker's real PostGIS could surface
that this sandbox's manually-installed Postgres 16 + PostGIS couldn't is a genuine
PostGIS version/behavior mismatch, which is low-probability but NOT zero, and is why
this is marked "not yet live-verified" rather than "verified":

- `python -m py_compile` on every new/changed file: clean.
- `pytest --collect-only`: all 500 tests collect with zero import errors.
- **Full suite run against a real (non-Docker) Postgres 16 + PostGIS: 500 passed, 0
  failed, 0 skipped** (464 baseline + 36 new). This is a stronger signal than Phase
  3's original authoring session had (which could only report 220 passed / 242
  skipped, since it had no reachable Postgres at all) - but it is still not the same
  Docker Postgres/PostGIS environment OpenCode verified Phase 1-3 against.
- Did NOT run the live app (`uvicorn main:app`) and hit the new endpoints with a real
  HTTP client outside of pytest's `ASGITransport` - only in-process ASGI requests
  were exercised. `ASGITransport` genuinely runs the full FastAPI dependency-
  injection/routing stack (this is not a mocked shortcut), but a real process
  boundary (real sockets, real uvicorn) was not exercised.
- Did NOT verify against the actual 88/122-located, 0-geometry real dataset from
  Phase 1-3's live runs - every DB-backed test here builds its own small synthetic
  agency/route/stops/trip, the same convention every other test file in this suite
  (`test_realtime_api.py`, `test_route_geometry.py`, etc.) already uses. This is
  consistent with the existing test suite's own established pattern, not a shortcut
  specific to this session.

## What the next verification session (OpenCode) should run

```
# From an environment with Docker + a reachable Postgres/PostGIS (no OSRM/Nominatim
# needed for Phase 4 specifically - only if re-verifying Phase 2/3 too):
alembic upgrade head          # confirms d4e5f6a7b8c9 is still the head - no new
                               # migration was added for Phase 4, so this should be a
                               # no-op if the DB is already there from Phase 3
pytest -q                     # expect 500 passed, 0 failed, 0 skipped
pytest tests/test_engine_geometry_interpolation.py tests/test_enhanced_realtime.py \
       tests/test_simulation_engine.py -q   # the Phase-4-specific subset in isolation
```

If the DB is currently sitting at the Phase 1-3 real-data baseline (2 agencies, 122
stops, 26 routes, 275 trips, etc.) rather than empty, remember the operational gotcha
every prior phase's handoff has repeated: pytest assumes an EMPTY baseline (rolled-
back transactions on top of empty tables) - clean `stop_times → trips → route_stops →
routes → stops → agencies` first, or the several tests elsewhere in the suite that
assert exact row counts / empty-list responses will fail for reasons unrelated to
Phase 4.

Beyond running the suite, worth spot-checking live (via `curl`/httpie against a
running `uvicorn main:app`, with at least one trip actually started via
`POST /api/transit/realtime/simulation/...`):
- `GET /api/transit/realtime/vehicles` returns `bearing`/`speed_kmh`/
  `route_short_name`/`current_stop_name` populated (not `null` for a route/stops
  that actually exist).
- `GET /api/transit/realtime/vehicles/{id}/eta` returns a plausible per-stop list
  for a real trip, with `delay_seconds: 0.0` throughout.
- If ever a real route acquires geometry (currently 0 do - see Phase 3's handoff),
  re-run this and confirm the vehicle position visibly follows the polyline rather
  than cutting straight lines between stops; there is no way to demonstrate this
  against real data until that precondition is met.

## What Remains

### Later phases (see §M, unchanged)
- **Phase 5** `POST /api/admin/trips/generate` daily-trip endpoint.
- **Phase 6** Frontend contract finalization (route geometry in journey legs, CORS,
  documented response shapes).

## Active Todo List (for next agent)
- [x] Phase 1 import pipeline + migrations + tests (431 passed)
- [x] Phase 2 geocoding service + script + provenance + tests + live run
      (447 passed, 88/122 stops located)
- [x] Phase 3 OSRM route geometry service + script + provenance columns + API
      exposure + tests + live-verified against real Docker PostGIS + OSRM
      (464 passed, 0 real routes eligible - correct, honest outcome)
- [x] Phase 4 enhanced realtime API (bearing/speed/route+stop names/ETA/delay) +
      optional Route.path polyline interpolation in `simulation/engine.py` + tests
      (500 passed in a non-Docker sandbox; NOT yet verified against Docker)
- [x] Phase 4 follow-up: verified against real Docker Postgres/PostGIS + live
      uvicorn spot-check (500 passed / 0 failed / 0 skipped; see the
      "Phase 4 VERIFIED" section below)
- [ ] Phase 5: admin daily-trip generation endpoint + tests
- [ ] Phase 6: frontend API contract finalization + tests
- [ ] Remember: clean transit tables before pytest after running any
      import/enrichment script that commits

---

# SESSION HANDOFF — Phase 4 VERIFIED (2026-08-18, verification agent / OpenCode)

## Status: Phase 4 (Enhanced Realtime API) verified against a live Docker
## PostgreSQL/PostGIS + a real uvicorn process. **500 tests pass, 0 failures,
## 0 skips** — identical to the authoring session's sandbox result, now confirmed
## against the same Docker environment OpenCode used for Phases 1–3.

## Environment used for this verification

- Windows 10, Docker Desktop running; `postgis/postgis:16-3.4` container started
  via the repository's existing `backend/docker-compose.yml` (no new/foreign DB
  setup was created). Python 3.13.3, `backend/.venv`, commands run from CMD.
- DB was at the empty pytest baseline (all tables 0 rows, alembic at
  `d4e5f6a7b8c9`) when verification started.

## Test results

- **Full suite** (`pytest -q`): **500 passed, 0 failed, 0 skipped** (~3–4 min).
  Run twice — once on the empty baseline and once after the live spot-check data
  was cleaned up — both identical.
- **Phase 4 subset** (`pytest tests/test_engine_geometry_interpolation.py
  tests/test_enhanced_realtime.py tests/test_simulation_engine.py -q`):
  **59 passed** (12 geometry-interpolation + 13 enhanced-realtime + 34
  simulation-engine). All 13 DB-backed `test_enhanced_realtime.py` tests
  executed against the REAL Docker PostGIS (they carry a `_database_reachable`
  guard that would have skipped them otherwise) — none skipped, including the
  synthetic-geometry wiring test `test_vehicle_position_follows_route_geometry_
  when_present`, which sets `Route.path` directly in the real DB.
- No test was weakened, deleted, or skipped to make the suite pass — nothing
  needed fixing. The only code changes in this tree are Claude's Phase 4
  implementation plus the plan.md handoff (this section).

## Migration status

- `alembic upgrade head` is clean/idempotent: a no-op on this DB (already at
  `d4e5f6a7b8c9`).
- Exactly **one** Alembic head: `d4e5f6a7b8c9` (add route geometry provenance,
  the Phase 3 migration). Linear chain, no unexpected migration changes, no new
  migration for Phase 4 (correct — plan.md section M says Phase 4 needs none).

## Live HTTP spot-check (real uvicorn, real sockets — the gap the authoring
## session explicitly could not close)

1. Imported the real canonical dataset (`scripts/import_transit_data.py
   --service-date 2026-08-18`): 2 agencies, 122 stops, 26 routes, 115
   route_stops, 275 trips, 6242 stop_times — identical to Phases 1–3.
2. **Confirmed the "no real geometry" precondition**: all 26 routes have
   `path IS NULL` and `geometry_source IS NULL`. Stop-coordinate coverage by
   route (import-only, before any geocoding): FR-01 0/26, FR-04 0/25, FR-07
   0/23, FR-14 0/18, Red Line 12/23. No real route has its full stop sequence
   located, so `Route.path` NULL for every real route is the correct, honest
   state — treated as expected, not a failure (matches Phase 3's handoff).
3. Started `uvicorn main:app` (real process, port 8000) against Docker PostGIS;
   lifespan routing-graph build succeeded.
4. Built a throwaway route `P4-CHK` from two REAL SEED_DATUM stops (Ammar Chowk,
   Bank Road) + a vehicle — the same pattern Phase 3's verification used for its
   throwaway geometry route. Started a trip via the real
   `POST /api/transit/realtime/simulation/routes/{id}/demo-trip` endpoint
   (status `active`, vehicle assigned).
5. `GET /api/transit/realtime/vehicles` and `GET /api/transit/realtime/vehicles
   /{id}` returned all enhanced fields populated over real HTTP:
   `route_short_name` ("P4-CHK"), `route_color` ("#00FF00"), `bearing`
   (335.18° — the correct Ammar Chowk→Bank Road heading), `speed_kmh` (20.0,
   matching the configured 20 km/h), `current_stop_name`/`next_stop_name`
   ("Ammar Chowk"/"Bank Road"), `scheduled_arrival_next_stop` ==
   `estimated_arrival_next_stop`, and `delay_seconds: 0.0`.
6. `GET /api/transit/realtime/vehicles/{id}/eta` returned exactly the one
   upcoming stop (Bank Road, sequence 2), `delay_seconds: 0.0`, scheduled ==
   estimated — and `404` for a non-existent vehicle id.
7. **Geometry wiring proven live**: set a bending `Route.path` LINESTRING on the
   throwaway route directly in PostGIS (no OSRM needed — real road geometry was
   NOT fabricated; this is the documented synthetic-path proof). The vehicle's
   bearing changed from 335° (straight stop-to-stop chord) to ~90° (following
   the polyline's first leg) and its location moved east along the polyline —
   proving `simulation.provider._load_route_geometry` → `compute_position_at(
   route_geometry=...)` → `point_along_polyline` end-to-end in production code
   against real PostGIS. With `path` reset to NULL (the real-data case), the
   bearing returns to the straight-line value — the `route_geometry=None`
   backward-compatible path verified live too.
8. Everything was torn down: uvicorn stopped, throwaway route/vehicle/trip
   removed, all transit tables truncated back to the empty pytest baseline, and
   the full suite re-run green afterwards.

## What remains

- **Phase 5** `POST /api/admin/trips/generate` daily-trip endpoint (plan.md
  section M-Phase 5). Not started, per the verification brief.
- The only thing that would change the "0 real routes have geometry" state is
  resolving the ~34 UNKNOWN stops (e.g. `Peshawar Morr (Interchange)` for the
  Red Line) so `scripts/generate_route_geometry.py` finds eligible routes; that
  is a data/enrichment task, not Phase 4 work.

---

### What Already Exists and Can Be Reused (Everything)


| Subsystem | Status | Reuse? |
|-----------|--------|--------|
| **Static transit models** (Agency, Route, Stop, RouteStop) | Complete, PostGIS-aware | YES — extend, don't replace |
| **Realtime models** (Vehicle, Trip, StopTime, VehiclePosition) | Complete | YES — the model is correct as-is |
| **Simulation engine** (`compute_position_at`) | Deterministic, DB-free | YES — add optional Route.path interpolation |
| **VehicleLocationProvider Protocol** | Clean abstraction | YES — future real-API provider plugs in here |
| **SimulationService** | Start/stop/record | YES — unchanged |
| **Routing graph** (`build_graph`, TransitGraph) | Complete with ride/walk edges | YES — rebuilt from enriched data |
| **Journey search** (Dijkstra, snapping) | Complete | YES — works with enriched graph |
| **Seeding/import pipeline** | JSON/CSV parsers, validation, importer | YES — extend for trips/stop_times/geometry |
| **All 406 tests** | Passing | MUST preserve |

### What Needs Extension (Not Replacement)

1. **`ImportDataset`**: Currently only agencies/stops/routes/route_stops. Must add trips, stop_times, service_calendars, route geometry.
2. **`Stop` model**: Needs `coordinate_source` and `coordinate_confidence` columns to track provenance.
3. **`Route` model**: `path` column exists but is always NULL. Needs population from OSM-derived geometry + provenance tracking.
4. **`RouteStop` model**: `distance_along_route_m` exists but is always NULL. Needs computation from route geometry.
5. **`simulation.timing`**: Currently uses flat 20 km/h for all routes. Must become route-aware when real timetable offsets exist.
6. **`simulation.engine`**: Currently interpolates straight-line between stops. Must optionally follow `Route.path` when available.
7. **Realtime API schemas**: Currently bare-bones. Needs bearing, scheduled arrival, ETA, delay, geometry.
8. **Static transit API**: `Route.path` is deliberately not serialized yet. Must expose GeoJSON.

---

## B. Data Architecture — How `transit_data.json` Becomes Database Records

### The Pipeline

```
transit_data.json (canonical research dataset)
    │
    ├── operators ──────► Agency rows
    ├── stops ──────────► Stop rows (with coordinate_source/confidence)
    ├── routes ─────────► Route rows
    ├── route_stops ────► RouteStop rows
    ├── trips ──────────► Trip + StopTime rows (for 4 researched routes)
    └── service_calendars ──► metadata for trip generation
```

### Key Design Decision: `transit_data.json` is the Single Source of Truth

- All data comes from this file. No fabrication.
- Stops with `latitude: null` remain null in the DB until geospatial enrichment fills them.
- Routes with `geometry: "UNKNOWN"` remain null in `Route.path` until geometry enrichment fills them.
- The 4 researched timetable patterns become real `Trip`/`StopTime` rows.
- Other routes get simulated timing (derived from speed/distance assumptions), clearly marked as such.

### Import Schema Extension

Extend `ImportDataset` in `seeding/import_schema.py`:

```python
@dataclass(frozen=True)
class ImportTripPattern:
    """A canonical trip pattern: one direction of one route, with headway metadata."""
    route_ref: str
    direction: str  # "forward" | "backward"
    headway_minutes: float
    total_trips_per_day: int
    first_trip_start: str  # "HH:MM:SS"
    last_trip_start: str | None  # "HH:MM:SS" or null
    source_pdf: str | None
    confidence: str

@dataclass(frozen=True)
class ImportStopTime:
    """One stop's arrival/departure offsets within a canonical trip pattern."""
    stop_ref: str
    sequence: int
    arrival_offset_s: int
    departure_offset_s: int

@dataclass(frozen=True)
class ImportDataset:
    # ... existing fields ...
    trip_patterns: tuple[ImportTripPattern, ...] = field(default_factory=tuple)
    # stop_times keyed by (route_ref, direction) -> tuple of ImportStopTime
    trip_stop_times: dict[tuple[str, str], tuple[ImportStopTime, ...]] = field(default_factory=dict)
```

### Parser Extension

Extend `seeding/parsers.py` to parse the `trips` array from `transit_data.json`:

- Each entry in `transit_data.json`'s `trips` array contains `route`, `direction`, `headway_minutes`, `total_trips_per_day`, `first_trip_start`, `last_trip_start`, `source_pdf`, `confidence`, and a `stop_times` sub-array.
- The parser creates `ImportTripPattern` + associated `ImportStopTime` tuples.

### Importer Extension

Extend `seeding/importer.py` to:

1. Import agencies, stops, routes, route_stops as before (get-or-create pattern).
2. For each `ImportTripPattern` with a matching Route row:
   - Generate `Trip` rows: one per trip-per-day, with `scheduled_start_time` = first_trip_start + n × headway_minutes.
   - Generate `StopTime` rows from the canonical stop_times, copying offsets verbatim.
3. Commit in a transaction.

### Validation Extension

Extend `seeding/validation.py` to validate:

- Trip patterns reference valid route_ref/stop_ref.
- Stop times are non-decreasing per trip pattern.
- First stop arrival_offset_s == 0.
- Last stop arrival == departure (no dwell at terminus).
- Headway > 0, total_trips > 0.

---

## C. Geospatial Enrichment Architecture

### Strategy: Nominatim (OSM) Geocoding with Provenance Tracking

**Stop coordinates will be obtained via OpenStreetMap Nominatim API**, then stored with full provenance.

### New Columns on `Stop` Model

```python
# backend/db/models/stop.py — additions
coordinate_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
# Values: "SEED_DATUM", "NOMINATIM", "MANUAL_VERIFIED", null (unknown)

coordinate_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
# Values: "OFFICIAL", "VERIFIED", "APPROXIMATE", "RECONSTRUCTED", "UNKNOWN"
# Carried from transit_data.json's confidence field, or set during enrichment.
```

### Enrichment Process

1. **Script** (`scripts/geocode_stops.py`): Reads all Stops with null coordinates from DB.
2. For each stop, queries Nominatim with `{stop_name} Islamabad` or `{stop_name} Rawalpindi`.
3. Validates result: must be within Islamabad/Rawalpindi bounding box (33.5°N–33.85°N, 73.0°E–73.3°E).
4. If multiple candidates: pick closest to district centroid, or flag for manual review.
5. Updates Stop: `location = ST_SetSRID(ST_MakePoint(lon, lat), 4326)`, `coordinate_source = "NOMINATIM"`, `coordinate_confidence = "APPROXIMATE"`.
6. Stops that fail geocoding remain null with `coordinate_confidence = "UNKNOWN"`.

### Why Nominatim

- Free, no API key required (polite usage: max 1 req/sec).
- OpenStreetMap data is the most complete source for Pakistani transit stops.
- ~80 stops to geocode — well within Nominatim's fair-use limits.
- Results are deterministic and reproducible (same query → same result).
- Alternative: Overpass API for bulk queries (more complex, same data source).

### What We Do NOT Do

- Do NOT fabricate coordinates.
- Do NOT assume all stops can be geocoded (some names are ambiguous).
- Do NOT geocode stops that already have APPROXIMATE coordinates from the seed dataset (keep those, they're known-good enough).
- Do NOT overwrite coordinates that already exist — only fill nulls.

---

## D. Route Geometry Architecture

### Strategy: OSRM Road-Snapping

**Route geometry (polyline) will be obtained by snapping the ordered stop sequence to road paths using OSRM.**

### Process

1. For each Route with ordered RouteStop stops that have coordinates:
   - Collect stop coordinates in sequence.
   - Query OSRM's `trip` or `route` service with these waypoints.
   - Receive a GeoJSON LineString or overview polyline.
   - Store in `Route.path` as PostGIS LINESTRING.
   - Set `geometry_source = "OSRM"` and `geometry_confidence = "OSM-DERIVED"`.

2. For routes where stops don't all have coordinates yet:
   - Leave `Route.path = NULL`.
   - `geometry_confidence = "UNKNOWN"`.

3. Compute `RouteStop.distance_along_route_m` from the geometry:
   - Walk the LineString, accumulating distance to each stop's nearest point on the path.

### OSRM Usage

- **Development**: Use OSRM demo server (`https://router.project-osrm.org`) — free, no key, rate-limited.
- **Production**: Self-host OSRM with OSM data for Pakistan (single `osrm-backend` Docker container, ~2GB data file).
- **Offline fallback**: Straight-line geometry between stops (marked `confidence = "RECONSTRUCTED"`).

### New Columns on `Route` Model

```python
# backend/db/models/route.py — additions
geometry_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
# Values: "OSRM", "MANUAL_VERIFIED", null (unknown)

geometry_confidence: Mapped[str | None] = mapped_column(String(20), nullable=True)
# Values: "OFFICIAL", "OSM-DERIVED", "RECONSTRUCTED", "UNKNOWN"
```

### Alternative Considered: Overpass API + Direct OSM Geometry

- Could query OSM for `route=bus` relations tagged for this network.
- Problem: CDA feeder routes likely don't have complete OSM route relations.
- OSRM snapping is more reliable for arbitrary stop sequences.
- Decision: OSRM for now; check OSM route relations as a future enhancement.

---

## E. Timetable/Trip Architecture

### How the 4 Researched Timetable Patterns Become Real Trip/StopTime Records

For each of FR-01, FR-04, FR-07, FR-14:

1. **One canonical pattern per direction** (from `transit_data.json`'s `trips` array).
2. **Generate N Trip rows**, one per trip-per-day:
   - `Trip.route_id` = the Route's UUID
   - `Trip.status` = "scheduled"
   - `Trip.scheduled_start_time` = first_trip_start + n × headway_minutes (for n = 0..N-1)
3. **Generate StopTime rows for each Trip**:
   - Copy the canonical stop_times verbatim (arrival_offset_s, departure_offset_s are relative to trip start).
   - `StopTime.stop_id` = matching Stop UUID (looked up by name during import).

### Example: FR-01 (16 trips/day, 60-min headway)

```
Trip 1: start = 07:15:00
  StopTime: cda_khanna_pul, arr=0, dep=0
  StopTime: cda_zia_masjid, arr=168, dep=188
  ... (26 stops)
  StopTime: cda_nust_metro_station, arr=3493, dep=3493

Trip 2: start = 08:15:00
  StopTime: cda_khanna_pul, arr=0, dep=0
  ... (identical offsets, shifted by 3600s)
```

### For Routes WITHOUT Timetable Data (Red/Orange/Blue/Green + 18 unfetched feeders)

- No Trip/StopTime rows are generated during import.
- The existing `build_trip_for_route` / `compute_stop_time_offsets` path remains available for on-demand demo trip creation (as it does today).
- These routes can still be displayed on the map (stops, route geometry) without trips.
- The simulation control API can create demo trips as needed.

### Future Timetable Additions

When more CDA PDFs are fetched:
1. Add new entries to `transit_data.json`.
2. Re-run import — the importer is idempotent (get-or-create for static data, replace for trips).
3. No schema changes needed.

---

## F. Simulation Architecture

### How the Existing Simulation Engine Consumes Real Data

**No fundamental changes to the simulation engine are needed.** The architecture already supports this:

1. **Real timetable available** (FR-01/04/07/14):
   - `Trip` rows exist with real `StopTime` offsets.
   - `load_trip_schedule()` loads them into `TripSchedule`.
   - `compute_position_at(schedule, elapsed_s)` works exactly as today.
   - Result: bus positions match real scheduled times.

2. **No real timetable** (demo trips):
   - `build_trip_for_route()` creates Trip + StopTimes from RouteStop order + speed/dwell assumptions.
   - `compute_position_at()` works identically.
   - Result: plausible but not real-world timing.

3. **Route.path available** (geometry enrichment done):
   - `compute_position_at()` can optionally interpolate along the polyline instead of straight-line.
   - When `Route.path` is NULL, falls back to current straight-line interpolation.
   - This is an **additive enhancement**, not a replacement.

### Specific Changes

1. **`simulation/engine.py`** — Add optional `route_geometry` parameter to `compute_position_at()`:
   ```python
   def compute_position_at(
       schedule: TripSchedule,
       elapsed_s: float,
       *,
       vehicle_id: uuid.UUID | None = None,
       as_of: datetime | None = None,
       route_geometry: list[tuple[float, float]] | None = None,  # NEW
   ) -> SimulatedPosition:
   ```
   When `route_geometry` is provided and the vehicle is `en_route`, interpolate along the polyline instead of straight-line between stops. When None, use current behavior.

2. **`simulation/provider.py`** — `SimulatedVehicleLocationProvider._position_for_trip()` optionally loads `Route.path` and passes it to `compute_position_at()`.

3. **`simulation/timing.py`** — No changes for routes with real timetable data (offsets come from DB). The `compute_stop_time_offsets()` function remains available for demo-trip creation.

### Multiple Simultaneous Buses

- Already fully supported by the existing architecture.
- Real headway data informs how many Trips should be created per route.
- For FR-04/FR-07 (97 trips/day, 10-min headway), that's ~10 concurrent trips during peak.
- The simulation control API or a seed script creates the fleet.

---

## G. Realtime API — Exact Endpoints and Response Contracts

### New Endpoints

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| `GET` | `/api/transit/routes/{route_id}/geometry` | GeoJSON LineString for a route | None |
| `GET` | `/api/transit/stops/{stop_id}/nearby` | Nearby stops by distance | None |
| `GET` | `/api/transit/realtime/vehicles/{vehicle_id}/eta` | ETA at next stops | None |
| `GET` | `/api/transit/realtime/fleet` | All active vehicles with full context | None |

### Modified Endpoints

**`GET /api/transit/routes/{route_id}`** — Add `geometry` field:
```json
{
  "id": "...",
  "short_name": "FR-04",
  "geometry": {
    "type": "LineString",
    "coordinates": [[73.065, 33.699], [73.072, 33.704], ...]
  },
  "geometry_confidence": "OSM-DERIVED",
  "stops": [...]
}
```

**`GET /api/transit/realtime/vehicles`** — Enhance `VehiclePositionRead`:
```json
{
  "vehicle_id": "...",
  "trip_id": "...",
  "route_id": "...",
  "route_short_name": "FR-04",
  "route_color": "#E53935",
  "location": {"latitude": 33.704, "longitude": 73.072},
  "bearing": 45.2,
  "speed_kmh": 18.5,
  "status": "en_route",
  "current_stop_id": "...",
  "current_stop_name": "Melody Market",
  "next_stop_id": "...",
  "next_stop_name": "Abpara Market",
  "scheduled_arrival_next_stop": "2026-08-16T14:32:00Z",
  "estimated_arrival_next_stop": "2026-08-16T14:32:00Z",
  "delay_seconds": 0,
  "elapsed_s": 1247.5,
  "as_of": "2026-08-16T14:27:07Z"
}
```

### Response Schema Definitions

```python
class RouteGeometryRead(BaseModel):
    geometry: dict | None  # GeoJSON LineString or null
    geometry_source: str | None
    geometry_confidence: str | None

class VehiclePositionRead(BaseModel):
    # ... existing fields ...
    bearing: float | None = None
    speed_kmh: float | None = None
    route_short_name: str | None = None
    route_color: str | None = None
    current_stop_name: str | None = None
    next_stop_name: str | None = None
    scheduled_arrival_next_stop: datetime | None = None
    estimated_arrival_next_stop: datetime | None = None
    delay_seconds: float | None = None

class ETARead(BaseModel):
    stop_id: uuid.UUID
    stop_name: str
    sequence: int
    scheduled_arrival: datetime
    estimated_arrival: datetime
    delay_seconds: float
```

---

## H. Map/Frontend Contract

### What the Frontend Receives to Render the Map

**1. Map Initialization / Static Transit Data:**
```
GET /api/transit/stops          → [{id, name, location: {lat, lon}, distance_m?}]
GET /api/transit/routes         → [{id, short_name, long_name, color, agency_id}]
GET /api/transit/routes/{id}    → {id, short_name, color, geometry: GeoJSON, stops: [...]}
GET /api/transit/agencies       → [{id, name, network_type}]
```

**2. Route Polylines (GeoJSON):**
```
GET /api/transit/routes/{id}/geometry → {
  type: "LineString",
  coordinates: [[lon, lat], ...],
  confidence: "OSM-DERIVED"
}
```

**3. Vehicle Markers (live positions):**
```
GET /api/transit/realtime/vehicles → [{
  vehicle_id,
  route_id,
  route_short_name,
  route_color,
  location: {latitude, longitude},
  bearing,
  status,
  current_stop_name,
  next_stop_name,
  scheduled_arrival_next_stop,
  estimated_arrival_next_stop,
  delay_seconds
}]
```

**4. Vehicle Details:**
```
GET /api/transit/realtime/vehicles/{id} → same shape as above
GET /api/transit/realtime/routes/{id}/vehicles → [same shape]
```

**5. ETAs:**
```
GET /api/transit/realtime/vehicles/{id}/eta → {
  vehicle_id,
  trip_id,
  etas: [{stop_id, stop_name, sequence, scheduled, estimated, delay}]
}
```

**6. Journey Search Results (existing, enhanced):**
```
POST /api/transit/journeys/search → {
  journeys: [{
    legs: [
      {type: "walk", from_location, to_location, distance_m, duration_s},
      {type: "ride", route: {id, short_name, color}, board_stop, alight_stop,
       intermediate_stops, duration_s, route_geometry: GeoJSON}
    ]
  }]
}
```

**7. Nearby Stops:**
```
GET /api/transit/stops?latitude=...&longitude=...&radius_m=500 → [{..., distance_m}]
```

---

## I. ETA/Delay Architecture

### Data Model

For simulated vehicles (deterministic):
- **Scheduled arrival** = `Trip.scheduled_start_time + StopTime.arrival_offset_s`
- **Simulated arrival** = identical to scheduled (deterministic, no randomness)
- **Estimated arrival** = identical to scheduled (for simulated vehicles)
- **Delay** = 0 always (for simulated vehicles)

This is the correct design because:
- The simulator IS the schedule. There's no "real" position to compare against.
- Delay only becomes meaningful when real vehicle data exists.
- The API contract is ready: `delay_seconds: 0` tells the frontend "no delay information."

### Future Real-vehicle Scenario

When real GPS feeds arrive:
- **Scheduled arrival** = from `StopTime.arrival_offset_s`
- **Actual arrival** = when vehicle actually passed the stop (from GPS feed)
- **Estimated arrival** = predicted based on current position + speed + distance
- **Delay** = estimated - scheduled (or actual - scheduled after the fact)

The `VehicleLocationProvider` abstraction already handles this — the real provider returns the same `SimulatedPosition` shape, and the API layer computes delay from scheduled vs. actual.

---

## J. Future Real-API Migration

### The Abstraction Boundary

```
Realtime API Layer
    │
    ├── VehicleLocationProvider Protocol  ←── THIS IS THE SWAP POINT
    │       │
    │       ├── SimulatedVehicleLocationProvider (today)
    │       └── RealGpsVehicleLocationProvider (future)
    │
    └── All consumers (realtime API, frontend, journey search)
         Never know which provider is behind the Protocol
```

### What Changes When Real GPS Arrives

1. Create `RealGpsVehicleLocationProvider` implementing `VehicleLocationProvider`.
2. Change `api/transit/realtime/dependencies.py`'s `get_vehicle_location_provider()` to return the real provider.
3. No API endpoints change. No frontend changes. No model changes.
4. The `delay_seconds` field naturally becomes non-zero when real data differs from schedule.

### Future Provider Considerations

- Real GPS data may come as GTFS-RT VehiclePositions feed.
- Parse into `SimulatedPosition`-compatible shape.
- May need to handle: stale data, out-of-order updates, gaps.
- The existing `VehicleLocationProvider` Protocol methods cover all these cases (return None for unknown, return empty list for nothing running).

---

## K. Database/Alembic Changes

### Migration 1: Extend Stop with coordinate provenance

```
ALTER TABLE stops ADD COLUMN coordinate_source VARCHAR(50);
ALTER TABLE stops ADD COLUMN coordinate_confidence VARCHAR(20);
```

### Migration 2: Extend Route with geometry provenance

```
ALTER TABLE routes ADD COLUMN geometry_source VARCHAR(50);
ALTER TABLE routes ADD COLUMN geometry_confidence VARCHAR(20);
```

### No Other Model Changes Required

- `Trip`/`StopTime` models are already correct for timetable data.
- `VehiclePosition` model is already correct.
- `RouteStop.distance_along_route_m` is already nullable — just needs population.

### Alembic Ordering

New migrations go after `4795c429e65f_add_users_fares_tickets.py` (the latest existing migration). Two separate migration files for clarity and atomicity.

---

## L. Testing Strategy

### Unit Tests (deterministic, no DB)

| Test | What it tests |
|------|--------------|
| `test_transit_data_parser.py` | Parsing `transit_data.json` into `ImportDataset` with trip patterns |
| `test_geocoding_service.py` | Geocoding logic (mocked Nominatim responses) |
| `test_route_geometry.py` | OSRM response parsing, LineString construction |
| `test_trip_generation.py` | Generating Trip/StopTime rows from ImportTripPattern |
| `test_engine_geometry_interpolation.py` | `compute_position_at` with route_geometry parameter |

### Integration Tests (DB required)

| Test | What it tests |
|------|--------------|
| `test_transit_data_import.py` | Full import pipeline: JSON → ImportDataset → DB |
| `test_geocode_stops_script.py` | Geocoding script against test DB (mocked Nominatim) |
| `test_route_geometry_import.py` | OSRM → Route.path population |
| `test_timetable_import.py` | Trip/StopTime generation from canonical patterns |
| `test_enhanced_realtime_api.py` | Enhanced VehiclePositionRead response shape |
| `test_route_geometry_api.py` | GeoJSON geometry endpoint |
| `test_eta_api.py` | ETA endpoint response shape |
| `test_nearby_stops.py` | Nearby stops with enriched coordinates |

### Preserving Existing Tests

- All 406 existing tests must continue passing.
- No model changes that break existing test fixtures.
- Import pipeline extensions are additive (new fields are optional).

---

## M. Implementation Phases

### Phase 1: Transit Data Import (Foundation)

**Goal:** Import `transit_data.json` into the database.

**Files to create/modify:**
- `backend/seeding/import_schema.py` — Add `ImportTripPattern`, `ImportStopTime` to `ImportDataset`
- `backend/seeding/parsers.py` — Parse trips/stop_times from JSON
- `backend/seeding/validation.py` — Validate trip patterns
- `backend/seeding/importer.py` — Import trip patterns → Trip/StopTime rows
- `backend/seeding/transit_data_importer.py` — New: dedicated importer for `transit_data.json` format
- `backend/scripts/import_transit_data.py` — CLI script
- `backend/tests/test_transit_data_import.py`

**Database changes:** None (schema is sufficient).

**APIs added:** None (uses existing admin/import endpoints).

**Tests:** Import all 28 routes, 97 stops, 4 timetable patterns. Verify Trip/StopTime row counts. Verify stop coordinates (null vs non-null). Verify idempotency.

**Dependencies:** None new.

**Expected result:** `transit_data.json` fully imported. 28 routes, 97 stops, 64+ Trip rows (16+25+23+18 canonical patterns, expanded to daily trip counts), corresponding StopTime rows.

**Commit message:** `feat: import transit_data.json into database with trip/timetable patterns`

---

### Phase 2: Geospatial Enrichment (Stop Coordinates)

**Goal:** Obtain coordinates for stops that currently have null lat/lon.

**Files to create/modify:**
- `backend/db/models/stop.py` — Add `coordinate_source`, `coordinate_confidence` columns
- `backend/alembic/versions/xxxx_add_stop_coordinate_provenance.py` — Migration
- `backend/seeding/geocoding.py` — New: Nominatim geocoding service
- `backend/scripts/geocode_stops.py` — CLI script
- `backend/tests/test_geocoding.py`

**Database changes:** 2 new columns on `stops` table.

**APIs added:** None (coordinates appear in existing endpoints automatically).

**Tests:** Geocode ~80 stops. Verify all APPROXIMATE stops unchanged. Verify geocoded stops within Islamabad/Rawalpindi bounds. Verify provenance tracking.

**Dependencies:** `httpx` (already in requirements.txt) for Nominatim API calls.

**Expected result:** ~60-70 of ~80 null-coordinate stops now have lat/lon. Remaining ~10-20 flagged as UNKNOWN.

**Commit message:** `feat: geocode transit stops via Nominatim with provenance tracking`

---

### Phase 3: Route Geometry (OSRM Snapping)

**Goal:** Obtain road-following polyline geometry for routes with complete stop coordinates.

**Files to create/modify:**
- `backend/db/models/route.py` — Add `geometry_source`, `geometry_confidence` columns
- `backend/alembic/versions/xxxx_add_route_geometry_provenance.py` — Migration
- `backend/seeding/route_geometry.py` — New: OSRM route-snapping service
- `backend/scripts/generate_route_geometry.py` — CLI script
- `backend/api/transit/router.py` — Expose `Route.path` as GeoJSON in route detail
- `backend/api/transit/schemas.py` — Add `geometry` field to `RouteDetail`
- `backend/tests/test_route_geometry.py`

**Database changes:** 2 new columns on `routes` table. `Route.path` populated for some routes.

**APIs added/changed:**
- `GET /api/transit/routes/{id}` — Response now includes `geometry` (GeoJSON LineString or null)
- `GET /api/transit/routes/{id}/geometry` — New endpoint returning just the geometry

**Tests:** Generate geometry for routes with complete stop coordinates. Verify GeoJSON LineString format. Verify RouteStop.distance_along_route_m computation. Verify existing route endpoints still work.

**Dependencies:** `httpx` (existing) for OSRM API calls.

**Expected result:** FR-01, FR-04, FR-07, FR-14 routes have road-following geometry. Red Line has geometry if all stops geocoded. Other routes remain NULL until stops are geocoded.

**Commit message:** `feat: generate route geometry via OSRM with provenance tracking`

---

### Phase 4: Enhanced Realtime API (Bearing, ETA, Delay)

**Goal:** Expose richer vehicle position data for the frontend map.

**Files to create/modify:**
- `backend/api/transit/realtime/schemas.py` — Enhance `VehiclePositionRead`
- `backend/api/transit/realtime/router.py` — Compute bearing, load stop names
- `backend/simulation/engine.py` — Add bearing computation, optional route_geometry interpolation
- `backend/simulation/provider.py` — Load Route.path, pass to engine
- `backend/api/transit/realtime/eta_router.py` — New: ETA endpoint
- `backend/tests/test_enhanced_realtime.py`

**Database changes:** None.

**APIs added/changed:**
- `GET /api/transit/realtime/vehicles` — Enhanced response with bearing, stop names, ETA, delay
- `GET /api/transit/realtime/vehicles/{id}` — Enhanced response
- `GET /api/transit/realtime/vehicles/{id}/eta` — New: per-stop ETA list

**Tests:** Verify bearing computation. Verify stop name resolution. Verify ETA calculation. Verify delay is 0 for simulated vehicles.

**Dependencies:** None new.

**Expected result:** Frontend receives all data needed to render vehicles with direction, next stop info, and arrival predictions.

**Commit message:** `feat: enhance realtime API with bearing, stop names, ETA, and delay`

---

### Phase 5: Trip Generation Admin Endpoint

**Goal:** Allow admin to generate daily trips from imported timetable patterns.

**Files to create/modify:**
- `backend/api/admin/router.py` — Add trip generation endpoint
- `backend/seeding/trip_generator.py` — New: generate daily trips from patterns
- `backend/tests/test_trip_generation.py`

**Database changes:** None (Trip/StopTime rows created by endpoint).

**APIs added:**
- `POST /api/admin/trips/generate` — Generate daily trips from imported patterns

**Tests:** Generate trips for FR-04. Verify correct count (97). Verify offsets match canonical pattern. Verify idempotency.

**Dependencies:** None new.

**Expected result:** Admin can populate the database with realistic daily trips.

**Commit message:** `feat: add admin endpoint for daily trip generation from timetable patterns`

---

### Phase 6: Frontend Integration Readiness

**Goal:** Finalize all API contracts the frontend needs.

**Files to create/modify:**
- `backend/api/transit/schemas.py` — Finalize all response schemas
- `backend/api/transit/realtime/schemas.py` — Finalize realtime schemas
- `backend/api/transit/journey_schemas.py` — Add route geometry to journey legs
- `backend/tests/test_frontend_contract.py` — Validate all response shapes

**Database changes:** None.

**APIs added/changed:**
- Journey search response includes route geometry per ride leg
- All endpoints return consistent, documented response shapes

**Tests:** Validate every endpoint response matches documented schema. Verify CORS headers. Verify no authentication required for public transit data.

**Dependencies:** None new.

**Expected result:** Frontend developer can integrate against stable, documented API contracts.

**Commit message:** `feat: finalize frontend API contracts for map integration`

---

## N. External Dependencies

| Dependency | Purpose | Required At | API Key? | Open/Self-Hosted? |
|-----------|---------|-------------|----------|-------------------|
| **Nominatim** | Stop geocoding | Build time (one-time script) | No (polite usage) | Open (OSM) |
| **OSRM demo** | Route geometry | Build time (one-time script) | No | Open (demo server) |
| **OSRM self-hosted** | Route geometry (production) | Runtime (optional) | No | Self-hosted Docker |
| **OpenStreetMap data** | OSRM routing data | Build time (for OSRM) | No | Open (ODbL) |
| **MapLibre** | Frontend map rendering | Frontend only | No | Open (BSD) |

### What Can Be Done Entirely Locally

- All backend code changes
- Database migrations
- Unit tests
- Integration tests (with Docker PostgreSQL/PostGIS)
- Trip generation
- Simulation

### What Requires Network Access (One-Time)

- Stop geocoding via Nominatim (one script run, ~80 requests at 1/sec = ~2 minutes)
- Route geometry via OSRM (one script run, ~28 routes)

---

## O. Risks / Unresolved Questions

### High Risk

1. **Ambiguous stop names**: Some stop names (e.g., "G-9 Markaz") may geocode to wrong locations or multiple candidates. Mitigation: validate within Islamabad/Rawalpindi bounding box; flag ambiguous results for manual review.

2. **Missing coordinates for key stops**: If critical Red Line interior stops (Waris Khan, Rehmanabad, etc.) can't be geocoded, the Red Line route geometry can't be generated. Mitigation: these are well-known locations; Nominatim should handle them. Worst case: manual coordinate entry for ~10 stops.

3. **OSRM accuracy for feeder routes**: Feeder routes may use narrow residential roads that OSRM doesn't weight correctly. Mitigation: mark geometry as `OSM-DERIVED`, not `OFFICIAL`.

### Medium Risk

4. **FR-07 ordering anomaly**: The `cda_nust_metro_station` stop in FR-07 appears between `cda_mehrabad` and `cda_bar_council` in the offset sequence, which may reflect a real routing quirk. Mitigation: import as-is from the official PDF; don't reorder.

5. **FR-14 truncated departure**: The `cda_cda_stop` departure time is null in the PDF. Mitigation: set departure = arrival for this stop (no dwell modeled).

6. **Red Line station count conflict**: 24 (official) vs. 23 (only ordered list found). Mitigation: import the 23 that are confirmed; note the discrepancy.

### Low Risk

7. **Rate limiting on Nominatim**: 80 requests at 1/sec is well within limits. No risk.

8. **OSRM demo server availability**: Free but may be slow or rate-limited. Mitigation: retry logic; fallback to straight-line geometry.

9. **Coordinate accuracy**: All coordinates are approximate, not survey-grade. This is acceptable for a transit planning app. Documented via `coordinate_confidence`.
