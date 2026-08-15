# Data, Seeding, Import & Admin Tooling

This document covers everything under `backend/data/`, `backend/seeding/`,
`backend/api/admin/`, `backend/api/dev/`, and `backend/scripts/` - the
data/seeding/development-tooling workstream. It does not repeat anything
already covered by the main `README.md` (transit data model, routing
architecture, etc.).

## Contents

- [Seeding demo data](#seeding-demo-data)
- [Resetting demo data](#resetting-demo-data)
- [Importing external data](#importing-external-data)
- [Validating data](#validating-data)
- [Rebuilding the routing graph](#rebuilding-the-routing-graph)
- [Dataset structure](#dataset-structure)
- [Manual integration steps](#manual-integration-steps)
- [Limitations](#limitations)

Every operation described here is available two ways: as a plain async
Python function (importable directly, e.g. from a script or another
module) and, once wired in (see
[Manual integration steps](#manual-integration-steps)), over HTTP via the
admin/dev API. Neither the admin nor dev router is registered on the
running application yet - see that section for why and how to change it.

## Seeding demo data

The demo dataset (`backend/data/seed_dataset.py`) is a small, deterministic,
geographically plausible transit network loosely modeled on the real
Islamabad Metrobus (blue line) and Rawalpindi Metrobus (red line) BRT
corridors, plus two short feeder routes:

| Route | Agency | Stops |
|---|---|---|
| `BL` — Pak Secretariat – Faizabad | Islamabad Metrobus | 6 |
| `RL` — Faizabad – Saddar | Rawalpindi Metrobus | 9 |
| `F-1` — Bank Road – Ammar Chowk Feeder | CDA Feeder Network | 3 |
| `F-2` — G-9 Markaz – Melody – G-10 Markaz Feeder | CDA Feeder Network | 3 |

This demonstrates, deliberately:

- **Multiple routes across multiple agencies.**
- **A same-stop transfer** at *Faizabad* (BL ↔ RL) and at *Melody* (BL ↔ F-2).
- **A walking-radius transfer** between *Saddar* (RL) and *Bank Road* (F-1) -
  two different stops, ~290m apart, within `routing.graph.WALKING_RADIUS_M`
  (400m) but not the same physical location, so a walking edge (not a
  shared stop) is what connects them.
- **Different routing objectives disagreeing**: `fewest_transfers` vs.
  `least_walking` vs. `fastest` should genuinely pick different paths for a
  Saddar ↔ Ammar Chowk search, thanks to the walking-transfer above.

**Apply it:**

```bash
cd backend
python scripts/seed_dev_db.py               # mode=insert (default)
```

or, once the admin router is wired in:

```
POST /api/admin/seed
{"mode": "insert"}
```

**Modes** (see `seeding/seed.py` docstrings for the full rationale):

- `insert` (default) — create only rows that don't already exist yet
  (checked by deterministic ID, see below). Already-present rows are left
  completely untouched. Safe to run repeatedly; a second run is a no-op.
- `replace` — delete every row the dataset owns, then re-insert it fresh.
  Use this after editing `seed_dataset.py`, so field changes (a renamed
  stop, a moved coordinate, a reordered route) actually take effect -
  `insert` mode would silently skip them.

**Determinism.** Every seeded row gets a UUID derived deterministically
from a stable key via `uuid.uuid5(SEED_NAMESPACE, ...)` (see
`data/seed_dataset.py`), not `uuid.uuid4()`. Re-seeding an empty database
always produces the exact same row IDs. This is also what makes both
`insert` (check "does this exact ID already exist") and `replace`/reset
(delete exactly the rows with these known IDs, and nothing else) safe.

## Resetting demo data

```bash
python scripts/seed_dev_db.py --reset
```

or `POST /api/admin/seed/reset` once wired in.

This deletes **only** the rows the seed dataset owns, identified by their
deterministic IDs - never a blanket "delete everything in these tables".
It is safe to run alongside unrelated data (from an import, or from
another workstream's data once merged) in the same tables; that data is
never touched. See `seeding/seed.py::clear_seed_data`'s docstring for the
exact cascade behavior.

`--status` reports how much of the seed dataset is currently present
without changing anything:

```bash
python scripts/seed_dev_db.py --status
```

## Importing external data

For data that isn't the curated demo dataset - e.g. a community or
government source - use the importer instead of seeding. It accepts a
clean, self-contained JSON or CSV shape (not GTFS; see
[Limitations](#limitations) for why).

**JSON** (`POST /api/admin/import`, or `seeding.parsers.parse_json_text` +
`seeding.importer.import_dataset` directly):

```json
{
  "agencies": [{"name": "Example Agency", "network_type": "brt"}],
  "stops": [
    {"ref": "s1", "name": "Example Stop A", "latitude": 33.70, "longitude": 73.05},
    {"ref": "s2", "name": "Example Stop B", "latitude": 33.71, "longitude": 73.06}
  ],
  "routes": [
    {"ref": "r1", "agency": "Example Agency", "short_name": "EX-1", "long_name": "A - B", "color": "#1565C0"}
  ],
  "route_stops": [
    {"route_ref": "r1", "stop_ref": "s1", "sequence": 1},
    {"route_ref": "r1", "stop_ref": "s2", "sequence": 2, "distance_along_route_m": 500}
  ]
}
```

Every top-level key is optional. `agency` on a route is a **name** (not a
ref) - it's matched against `agencies[].name` or auto-created if not
listed there.

**CSV** (`POST /api/admin/import/csv`, multipart form fields `agencies`,
`stops`, `routes`, `route_stops`; any may be omitted):

```
agencies.csv:     name, network_type
stops.csv:        ref, name, latitude, longitude
routes.csv:        ref, agency, short_name, long_name, color
route_stops.csv:  route_ref, stop_ref, sequence, distance_along_route_m
```

**Entity matching** (how "create vs. update" is decided - see
`seeding/importer.py`'s module docstring for the full rationale):

- Agency: matched by `name` (an existing DB `UNIQUE` constraint).
- Route: matched by `(agency, short_name)` (an existing DB `UNIQUE`
  constraint).
- Stop: matched by exact `name` - an **application-level heuristic**, not
  a DB constraint (see [Limitations](#limitations)).
- RouteStop: matched by `(route, sequence)` (an existing DB `UNIQUE`
  constraint).

**Transactions.** The whole dataset is validated first
(see [Validating data](#validating-data)); if anything is invalid, nothing
is written at all. Persistence then runs in one transaction - if it fails
partway through, everything is rolled back, never left partially applied.

## Validating data

`seeding.validation.validate_dataset` runs automatically as the first
step of every import, and is also available standalone as a dry run
(`POST /api/dev/validate`, same request body shape as `/admin/import`, but
nothing is written).

Checks performed (see `seeding/validation.py` for the exact rules):

- duplicate route-stop sequence
- invalid sequence ordering (non-positive/non-integer; a gap is a
  *warning*, not an error - RouteStop's `sequence` only needs to be
  monotonic, not contiguous)
- missing route/stop references
- invalid coordinates / invalid geometry (non-finite, or out of
  `[-90, 90]` / `[-180, 180]`)
- routes with fewer than 2 valid stops (can't form a ride edge)
- duplicate identifiers (agency name, stop ref, route ref)

`POST /api/dev/validate/seed` runs the same check against the demo dataset
itself - a sanity check for anyone editing `data/seed_dataset.py`.

## Rebuilding the routing graph

Static data inserted after the application has started (via seeding or
import) isn't picked up automatically - the cached `TransitGraph` on
`app.state` is built once at startup (see `api/graph_state.py`). To
refresh it without restarting the server:

```
POST /api/admin/graph/rebuild
```

This calls the **existing** `api.graph_state.build_and_store_graph(app)` -
the same function `main.py`'s lifespan calls at startup - so there is
exactly one code path that ever constructs a `TransitGraph`; this
workstream adds no second one. See
[Manual integration steps](#manual-integration-steps) for wiring the
endpoint in.

Without the admin router wired in yet, either restart the server (which
re-runs the startup lifespan, rebuilding the graph automatically) or
verify offline with:

```bash
python scripts/verify_graph_buildable.py
```

(a read-only smoke test around `routing.graph.build_graph` - it never
touches a live `app.state`; see that script's docstring for exactly why
it's structured that way.)

## Dataset structure

Both the seed dataset and any import ultimately populate the same four
existing tables (owned by the routing/models workstream, not this one -
see the main `README.md` §11/§12 for their full definitions):

```
agencies  --< routes  --< route_stops >--  stops
```

- An `Agency` owns zero or more `Route`s.
- A `Route` has an ordered sequence of `Stop`s via `RouteStop.sequence`
  (1-based or otherwise monotonic - never row-insertion order).
- A `Stop` can appear on multiple routes (that's how transfers/shared
  stops work) and, in principle, more than once on the same route (a loop
  route revisiting a stop) - `RouteStop` is not unique on `(route, stop)`,
  only on `(route, sequence)`.

## Manual integration steps

Everything in `backend/api/admin/` and `backend/api/dev/` defines
`APIRouter` objects only - **neither is registered on the running
application**. This is deliberate (see both routers' module docstrings):
this workstream is not permitted to modify `api/router.py`, `main.py`, or
implement authentication, and every admin operation is either destructive
or otherwise inappropriate to expose publicly without auth.

To wire them in (in whichever later step adds authentication/production
routing decisions):

```python
# api/router.py (or wherever appropriate once auth exists)
from api.admin.router import router as admin_router
from api.dev.router import router as dev_router

api_router.include_router(admin_router)  # -> /api/admin/...
api_router.include_router(dev_router)    # -> /api/dev/...
```

Add authentication/authorization in front of at least the admin router
before exposing it anywhere but a local/trusted development environment.

## Limitations

- **Coordinates are approximate, not surveyed.** `data/seed_dataset.py`
  uses hand-picked coordinates for real Islamabad/Rawalpindi place names -
  geographically plausible (correct relative positions, real names,
  smooth corridor paths) but not GTFS/survey-grade positions. Fine for a
  demo; not for production routing accuracy.
- **Stop matching on import is by exact name**, not a formal external ID
  (there is no GTFS-style `stop_id` in this schema yet, and building one
  was explicitly out of scope - "do not build a complete GTFS ecosystem
  unless the repository actually requires it"). Renaming a stop between
  imports, or two sources describing the same physical stop under
  different names, creates a second `Stop` row rather than updating the
  first.
- **Not a GTFS importer.** The CSV/JSON shape here is a clean MVP format,
  not GTFS's `stops.txt`/`routes.txt`/`trips.txt`/`stop_times.txt`. A real
  GTFS feed would need its own translation step into this shape (or a
  dedicated GTFS parser, later, if the project actually needs one).
- **No scheduling/timing data.** Only the static route/stop network is
  covered - no `StopTime`, headways, or calendars (matches the rest of
  the current backend's scope).
- **No authentication.** See
  [Manual integration steps](#manual-integration-steps) - do not expose
  the admin router without adding some.
