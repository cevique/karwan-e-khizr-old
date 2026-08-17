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
