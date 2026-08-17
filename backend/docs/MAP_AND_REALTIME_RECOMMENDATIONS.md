# MAP_AND_REALTIME_RECOMMENDATIONS.md

Specification only — no implementation. This document assumes TRANSIT_RESEARCH.md and
DATA_GAPS.md have already been read.

> **UPDATE (this revision):** Phase 3 of `backend/plan.md` implemented §A.2's
> road-snapping fallback (option 3 below) and §B's route-geometry API exposure —
> `seeding/route_geometry.py`, `scripts/generate_route_geometry.py`, and
> `GET /transit/routes/{id}` / `GET /transit/routes/{id}/geometry` all now exist in
> the backend. §A.1 (OSM query for the real physical BRT alignment) and §A.2's options
> 1–2 were NOT pursued — the implementation went straight to OSRM road-snapping
> (option 3) rather than first checking for a real-alignment OSM relation, so that
> distinction (§A.2) is still open work, not something this update resolves. The live
> generation run against the real database WAS performed on 2026-08-17 and verified
> end-to-end (live Docker PostGIS + outbound OSRM access): the OSRM provider returned a
> valid GeoJSON `LineString`, PostGIS accepted the generated `Route.path`, provenance
> (`geometry_source`/`geometry_confidence` = `OSRM`/`OSM-DERIVED`) and per-stop
> `RouteStop.distance_along_route_m` were persisted, re-running was idempotent,
> `--dry-run` wrote nothing, and `--limit` worked. However, **no *real* route received
> geometry**: after Phase 2's geocoding (88/122 stops located), no route's full ordered
> stop sequence is located yet (Red Line is 1 stop short, FR routes 4–10 short — see
> DATA_GAPS.md §6's update note for the per-route counts). This is the correct, honest
> state: the script never fabricates a line for a route with an unlocated stop.

> **UPDATE (earlier revision):** a follow-up pass found official, stop-level CDA feeder-
> route timetable PDFs (DATA_GAPS.md §0). Worth stating explicitly here since it's
> easy to assume otherwise: **those PDFs give stop names and times only — no
> coordinates, no geometry.** Nothing in §A/§B below changes as a result; the map/
> geometry problem is exactly as open as it was before, just for a network whose
> timetable is now much better understood.

---

## A. Real map architecture

### A.1 Map technology
The project's own top-level `README.md` (§17 "Map Technology Evaluation") already made
and documented this decision: **MapLibre Native (React Native bindings) + OpenStreetMap-
derived vector tiles**, chosen specifically over Google Maps/Mapbox/`react-native-maps`
to avoid an API-key/billing dependency and licensing risk for a project whose long-term
goal is being an independent public transit product, not just a hackathon demo. This
research found no reason to revisit that decision and reaffirms it. Key implications
carried forward here:

- **No API key required for basic use** — either a free/public OSM-derived vector tile
  source (e.g. a public MapLibre-compatible demo tile server, suitable for a demo but
  not guaranteed-available/rate-limit-safe for real deployment) or self-hosted tiles
  (e.g. via `tileserver-gl` against a locally-generated `.mbtiles` extract of the
  Islamabad/Rawalpindi region — small enough to self-host given the limited geographic
  scope) if time allows.
- **Licensing**: OSM data is © OpenStreetMap contributors under the Open Database
  License (ODbL) — any deployed map using OSM-derived tiles/data must carry OSM
  attribution (a standard, small requirement, not a blocker).
- **Full control over custom layers** — stops, route polylines, simulated/real vehicle
  markers, the user's live location, and the selected-journey path are all custom
  layers the app draws on top of the base map; none of them depend on a particular
  base-map provider once MapLibre is the rendering layer.
- If this is ever deployed at real public-transit scale (not just hackathon/demo), a
  managed OSM vector-tile hosting service (there are several with generous free tiers
  aimed at exactly this use case) is a reasonable middle ground between "fully
  self-hosted" and "commercial map SDK" — worth evaluating **later**, not now; not
  assumed or required for the current scope.

### A.2 OpenStreetMap usage for route geometry (concrete next research/implementation step)

**Status: option 3 below is IMPLEMENTED** (`seeding/route_geometry.py` +
`scripts/generate_route_geometry.py`, Phase 3). **Options 1–2 (checking for a real
mapped alignment before falling back to road-snapping) were NOT done** — the
implementation went straight to OSRM road-snapping. This is a real, still-open gap:
road-snapped geometry is a strictly worse approximation than the BRT corridors' real
physical alignment where one is actually mapped in OSM (elevated/trenched sections
especially), so options 1–2 remain worth doing as a follow-up, and any route currently
tagged `geometry_confidence: "OSM-DERIVED"` in the database should be treated as "best
available today," not "as good as this could get."

This research pass did not have live Overpass API access. The concrete next step
(either for OpenCode directly, or a short follow-up research pass) is:

1. Query Overpass for `route=bus` relations tagged with names/refs matching this
   network within a bounding box covering Islamabad + Rawalpindi, e.g.:
   ```
   [out:json][timeout:60];
   area["name"="Islamabad"]->.a;
   area["name"="Rawalpindi"]->.b;
   (
     relation["route"="bus"](area.a);
     relation["route"="bus"](area.b);
   );
   out body;
   >;
   out skel qt;
   ```
   filtered/inspected for anything named/tagged with "Metrobus", "Red Line", "Orange
   Line", "BRT", or the `FR-*` codes.
2. Separately check for the **physical dedicated busway infrastructure** itself
   (distinct from a `route=bus` relation) — BRT corridors are often mapped as
   `highway=*` ways with `bus=designated`/`busway=*`/similar tags even where no transit
   route relation exists yet. If found, this is a **strictly better** geometry source
   than reconstructing from stops, since it's the actual physical alignment (including
   elevated/trench sections that a road-snapped route would not follow).
3. Where neither exists, fall back to **road-snapping through the ordered stop
   sequence** using an OSM-based routing engine (OSRM, Valhalla, or GraphHopper against
   a local Islamabad/Rawalpindi OSM extract). The public OSRM demo server is fine for
   prototyping this reconstruction step by hand, but should not be depended on for
   production/runtime use (no SLA, rate-limited, not intended for that).
4. Whichever geometry results, tag it in `transit_data.json`/`Route.path` with an
   honest confidence level: `OFFICIAL` (found as a real BRT-alignment mapping),
   `OSM-DERIVED` (found as an actual `route=bus` relation, but possibly imprecise),
   or `RECONSTRUCTED` (road-snapped through stops, not a real mapped alignment) — never
   silently upgraded to look more authoritative than it is.

   **Naming note (Phase 3 implementation deviates from this list):** the implemented
   `db/models/route.py` uses `"OSM-DERIVED"` for the OSRM road-snap outcome (point 3
   above), not `"RECONSTRUCTED"` as recommended here. This wasn't a deliberate
   reinterpretation — it's an inconsistency between this recommendations doc and the
   actual schema, flagged here rather than silently resolved either way. If options
   1–2 (a real mapped alignment) are ever implemented, they'll need their own distinct
   confidence value (this doc's `OFFICIAL`, or reuse of the model's existing `path`
   provenance fields with a value not yet in use) to stay distinguishable from the
   road-snapped `OSM-DERIVED` result already in the database.

### A.3 Backend vs. frontend responsibilities
- **Backend** owns: canonical stop/route/geometry data, computing the selected
  journey's path (walk legs + ride legs + transfer points), and simulated/real vehicle
  positions. All of this should be served as plain lat/lng (for points) or GeoJSON
  (for lines/polylines) — coordinate systems the mobile client can hand straight to
  MapLibre without further transformation.
- **Frontend** owns: rendering, camera/viewport management, live device-location
  sensing (see §C), and interaction (tapping a stop/vehicle marker). The backend
  should never need to know about screen coordinates, zoom levels, or tile URLs.

## B. Geographic backend API requirements

For each of the following, "expose" means: return in a shape a MapLibre-based client
can render with minimal client-side transformation. None of this needs to be a single
endpoint — additive changes to the existing `api/transit/` routers are sufficient.

- **Stops**: already served as `{latitude, longitude}` via `StopRead`/`Coordinates`
  (`api/transit/schemas.py`) — sufficient as-is for point markers. No change needed
  here beyond populating more real stop coordinates as they become available (§7 of
  DATA_GAPS.md).
- **Routes**: **IMPLEMENTED as of Phase 3** — `Route.path` is now exposed as GeoJSON
  via `GET /transit/routes/{id}` (embedded `geometry` field) and
  `GET /transit/routes/{id}/geometry` (standalone), returning
  `{type, coordinates, geometry_source, geometry_confidence}`, explicitly null for a
  route with no geometry generated yet — see `api/transit/schemas.py`'s
  `RouteGeometryRead` and `backend/plan.md`'s Phase 3 handoff. Populating `path` itself
  was verified working end-to-end against live OSRM + PostGIS on 2026-08-17; no *real*
  route has `path` populated yet only because no route's full stop sequence is located
  (§A.2's status note above, per-route counts in DATA_GAPS.md §6).
  (§A.2), it should be exposed as a GeoJSON `LineString` (or `null` if not yet
  available for that route) — additive to the existing `RouteDetail`/`RouteListItem`
  schemas, not a breaking change to them.
- **Route geometry confidence**: **IMPLEMENTED as of Phase 3** — `geometry_confidence`
  (and `geometry_source`) are exposed alongside `coordinates` in `RouteGeometryRead`,
  exactly as recommended here. The frontend does not yet do anything differently based
  on the value (that's a frontend/Phase 6 decision, not a backend one), but the data is
  there to support it.
- **Journeys**: a computed itinerary (existing `routing`/`api/transit/journeys.py`
  subsystem) should expose, per leg: leg type (walk/ride), the specific route+stop
  range for a ride leg (so the frontend can slice that route's own polyline to just
  the ridden segment, rather than the backend needing to compute and return a
  sub-polyline itself — cheaper and simpler on both sides), and a walk leg's own
  straight-line or (if ever available) road-following path.
- **Walking segments**: the existing walking-connection logic
  (`routing.providers.StraightLineWalkingProvider`) computes straight-line walking
  distances/times only. For map display, a straight line between two stops is a
  reasonable, honest approximation for the short walking-radius distances involved
  (≤400 m, per `routing.graph.WALKING_RADIUS_M`) — no need to introduce a
  pedestrian-routing dependency just for map rendering; label it as a straight-line
  approximation if the frontend ever renders it as a path rather than just two
  connected markers.
- **Simulated vehicles**: already served via `GET /transit/realtime/vehicles` and
  `/vehicles/{id}` with `{location, status, current_stop_id, next_stop_id, elapsed_s,
  as_of}` (`VehiclePositionRead`) — sufficient shape for a moving marker. See §D for
  what else a richer map view would want.
- **Eventually real vehicles**: same shape, same endpoints — the
  `VehicleLocationProvider` abstraction already guarantees this requires no API
  contract change when a real provider is substituted, only a `source`/similar field
  addition (simulated vs real) if the frontend needs to visually distinguish them —
  worth reserving that field name now even if unused until then.

## C. Live user location

- The user's own live GPS location is a **frontend-only** concern — MapLibre/the
  mobile OS location APIS supply it directly to the map layer; the backend has no need
  to know it **except** as an input to journey search (origin = current location) or
  nearby-stops search (`GET /transit/stops?latitude=...&longitude=...`, which the
  existing router already supports).
- No backend storage of live user location is implied or recommended beyond what's
  already needed for a single journey-search/nearby-stops request-response — do not
  introduce a location-history feature as part of this work; it's out of scope and
  raises privacy considerations not addressed anywhere else in this research.

## D. Simulation visualization

For the frontend to render a simulated vehicle usefully (marker + its route + heading +
current/next stop + schedule context), the existing `VehiclePositionRead` payload
already carries `location`, `status`, `current_stop_id`, `next_stop_id`, `route_id`,
`trip_id`, `elapsed_s`, `as_of`. To fully support the brief's requirement list
("vehicle marker, route, direction, current position, current trip, next stop,
scheduled arrival, simulated arrival, delay"), consider (additive, not breaking):

- **Direction/heading**: not currently computed anywhere. Derivable client-side from
  two consecutive position readings, or server-side from the bearing between the
  current interpolated point and the next stop (or the next point along `Route.path`,
  once that exists) — a small, self-contained addition to
  `simulation.engine.compute_position_at`'s output, not a redesign.
- **Scheduled arrival at next stop**: already implicitly available —
  `StopTime.arrival_offset_s` for `next_stop_id`, converted to a wall-clock time via
  `Trip.scheduled_start_time + arrival_offset_s`. Worth exposing directly in
  `VehiclePositionRead` (e.g. `next_stop_scheduled_arrival`) rather than making the
  frontend reconstruct it from three separate values.
- **Simulated/predicted arrival**: for the simulator alone (no real GPS yet), simulated
  arrival *is* scheduled arrival — there's no separate "predicted" concept until a real
  feed exists to disagree with the schedule. Do not invent a fake predicted-vs-
  scheduled delay from the simulator alone; that would misrepresent the simulator as
  more capable than it is (see §E).
- **Delay**: `0` / absent for every simulated vehicle, by construction, until real data
  exists to compare against (§E) — again, do not synthesize a fake delay for demo
  purposes; a demo can *narrate* "this is what delay will look like once real data
  exists" without the backend actually returning fabricated delay values.

## E. Future realtime integration

No implementation now — this is the seam design for later, so the eventual real
integration doesn't force an API-breaking change.

- **Actual vehicle positions**: a future `RealGpsVehicleLocationProvider` implementing
  the existing `VehicleLocationProvider` Protocol
  (`simulation/provider.py`) is the entire integration surface needed on the read
  side — no caller (API router, journey/ETA logic) should need to change.
- **Trip updates / stop-time updates**: GTFS-Realtime's `TripUpdate` concept (a
  real-time-adjusted arrival/departure per stop, relative to the static schedule) maps
  directly onto this project's existing `Trip`/`StopTime` shape — a future real feed's
  trip updates would most naturally be stored as *additional* rows/fields alongside
  the existing scheduled `StopTime` (e.g. a parallel `predicted_arrival_offset_s`), not
  by overwriting the scheduled value — preserving exactly the STATIC vs SCHEDULED vs
  REALTIME vs PREDICTED distinction the brief calls out. Do not implement this now;
  just don't design anything that would make it awkward later (e.g. don't overload
  `StopTime.arrival_offset_s` to sometimes mean "predicted" — keep it exclusively
  "scheduled/assumed").
- **Service alerts**: GTFS-Realtime's `Alert` concept (a free-text or coded
  service-disruption notice, e.g. "breakdown," "traffic congestion," "road closure")
  has no current data source for this network — do not build a delay-reason feature
  ahead of an actual source for delay reasons, and per the research brief's own
  instruction, never infer/invent a delay reason from GPS position alone once real
  data does exist.
- **Delay = actual/predicted − scheduled**: once a real feed's predicted arrival
  exists, delay is a pure computation from two existing values (predicted −
  `Trip.scheduled_start_time + StopTime.arrival_offset_s`) — no new architecture
  needed, just the arithmetic, once both sides of the subtraction are real.
- **ETA**: for a *scheduled* ETA today (no real data), this is exactly what
  `simulation.engine.compute_position_at` plus the relevant `StopTime.arrival_offset_s`
  already gives you — no gap. For a *predicted* ETA once real data exists, it comes
  from whatever the real feed provides directly (GTFS-Realtime `TripUpdate.StopTimeUpdate`
  typically carries a predicted arrival/departure directly, rather than requiring the
  consumer to compute it from a raw position) — do not build a "predict ETA from
  vehicle position + assumed speed" engine now; that's a distinct, more complex
  feature explicitly out of scope per the research brief's Non-Goals (no ML-based
  ETA/traffic prediction).
