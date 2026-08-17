# SIMULATION_DATA_SPEC.md

How the researched transit data (`transit_data.json`) should eventually map into the
existing backend's simulation architecture. **This was originally specification-only —
Phase 3 of `backend/plan.md` has since implemented the route-geometry-generation half
of it** (`seeding/route_geometry.py`, `scripts/generate_route_geometry.py`,
`Route.geometry_source`/`geometry_confidence`); the rest (§2 point 2's
`simulation.engine` polyline-interpolation extension, and the trip-import mechanics in
§1) remains specification-only, planned for a later phase. See the update note below
and `backend/plan.md`'s Phase 3 handoff for exact status.

> **UPDATE (this revision — Phase 3 implementation status):** the route-geometry
> generation mechanism described in §1 ("route geometry") and referenced in §2 point 2
> now EXISTS in code (`seeding/route_geometry.py` + `scripts/generate_route_geometry.py`,
> using OSRM road-snapping — see MAP_AND_REALTIME_RECOMMENDATIONS.md §A.2 for how this
> relates to the "check for a real mapped alignment first" recommendation, which was
> NOT implemented). The live generation run WAS performed on 2026-08-17 and verified
> end-to-end against live Docker PostGIS + the real OSRM public server: valid GeoJSON
> `LineString` returned, `Route.path` accepted by PostGIS, provenance
> (`geometry_source="OSRM"`/`geometry_confidence="OSM-DERIVED"`) and
> `RouteStop.distance_along_route_m` persisted, idempotent re-run, `--dry-run` wrote
> nothing, `--limit` respected. However `Route.path` is still `NULL` for every *real*
> route in the live database: after Phase 2's geocoding (88/122 stops located), no
> route's full ordered stop sequence is located yet (Red Line 1 short, FR-01 10, FR-04 4,
> FR-07 9, FR-14 10 — per-route counts in DATA_GAPS.md §6). `simulation.engine`'s
> polyline-interpolation extension (§2 point 2) is explicitly NOT part of Phase 3 and
> remains unimplemented — that's Phase 4.

> **UPDATE (earlier revision):** `transit_data.json` now contains REAL, officially-sourced
> stop-level trip data for 4 CDA feeder routes (FR-01, FR-04, FR-07, FR-14), stored as
> one canonical stop-time pattern per route/direction plus the service parameters
> needed to regenerate the full day's real trips. §1 and §2 below are updated to
> describe how this changes (and doesn't change) the entity mapping. This does not
> apply to the four main Metrobus lines (Red/Orange/Blue/Green) or the other 18 CDA
> feeder routes, which still have no stop-level timetable in this dataset — §3 onward
> is unchanged and still describes the assumption-based approach for those.

---

## 1. Entity mapping

```
official route (Wikipedia table / CDA PDF)
    -> db.models.Route  (agency_id, short_name, long_name, color, path)

ordered official stops (rehbar.pk table, cross-checked; CDA PDF names)
    -> db.models.Stop   (name, location)
    -> db.models.RouteStop  (route_id, stop_id, sequence, distance_along_route_m)

published trip schedule
    -> EXISTS for 4 CDA feeder routes (FR-01, FR-04, FR-07, FR-14 — see
       DATA_GAPS.md §0) as one canonical stop-time pattern per route/direction, plus
       headway_min/total_trips_per_day/first_trip_start/last_trip_start. To become
       real db.models.Trip / db.models.StopTime rows: for each of
       total_trips_per_day trips, create one Trip with
       scheduled_start_time = first_trip_start + n * headway_min (n = 0..total_trips_per_day-1,
       capped so the last generated start_time does not exceed last_trip_start where
       given), and StopTime rows copying the canonical pattern's arrival_offset_s /
       departure_offset_s verbatim (they are already offsets from trip start, so no
       recomputation is needed — just copy them onto each generated Trip). This is a
       direct, mechanical expansion of real data, not simulation.timing's assumption-
       based computation.
    -> DOES NOT EXIST for the four main Metrobus lines (Red/Orange/Blue/Green) or the
       other 18 CDA feeder routes not yet fetched (see DATA_GAPS.md §1, §5) -> no real
       db.models.Trip / db.models.StopTime can be sourced for those; they continue to
       be simulation-generated, as they already are today via
       simulation.trip_builder.build_trip_for_route + simulation.timing.

route geometry
    -> db.models.Route.path (LINESTRING) -- POPULATION MECHANISM NOW IMPLEMENTED
       AND LIVE-VERIFIED (Phase 3, backend/plan.md): seeding/route_geometry.py +
       scripts/generate_route_geometry.py generate it via OSRM road-snapping for
       any route whose full ordered stop sequence is already located. The live run
       (2026-08-17) confirmed the end-to-end path works against real OSRM + PostGIS,
       but `path` is still NULL for every real route because no route's full stop
       sequence is located yet (Red Line 1 stop short, FR routes 4-10 short - see
       DATA_GAPS.md §6) - a data-availability gap, not a missing-capability or
       execution gap. Also new: `Route.geometry_source`
       / `Route.geometry_confidence` columns record provenance per route (see §9 of
       TRANSIT_RESEARCH.md, §A of MAP_AND_REALTIME_RECOMMENDATIONS.md for the
       OSRM-vs-real-alignment distinction this doesn't yet resolve).
    -> consumed by an EXTENDED simulation.engine.compute_position_at (see §2 below)
       for interpolation, once populated -- THIS EXTENSION IS STILL NOT DONE
       (it's Phase 4 in backend/plan.md, not Phase 3); `simulation.engine` as of
       this revision still only ever interpolates straight-line between adjacent
       stops, regardless of whether `Route.path` is populated for that route.

simulated vehicle
    -> db.models.Vehicle + db.models.VehiclePosition (unchanged; already fully
       implemented and does not need new data to keep working)
```

## 2. What changes in the existing simulation architecture, and what doesn't

**Does not need to change:**
- `simulation.engine.compute_position_at`'s overall state machine (not_started /
  at_stop / en_route / completed) and its `TripSchedule`/`ScheduleStop` input shape.
- `simulation.provider.SimulatedVehicleLocationProvider` / `VehicleLocationProvider`
  Protocol.
- `simulation.service.SimulationService`'s control-plane (`start_trip`, `stop_trip`,
  `record_position`).
- The `Trip`/`StopTime` schema itself — it already models "seconds since trip start"
  offsets generically enough to hold either simulation-assumed or (later) real
  schedule-derived values without a migration.

**Needs to change (additively):**
1. `simulation.timing.compute_stop_time_offsets`'s speed/dwell assumption should become
   **route-aware** rather than one global constant (`SIMULATED_VEHICLE_SPEED_KMH =
   20.0` today, applied identically to a dedicated-lane BRT corridor and a
   mixed-traffic feeder route). Concretely:
   - Keep the function's signature and algorithm the same (still: prefer
     `distance_along_route_m` deltas over Haversine fallback; still: flat dwell at
     intermediate stops only).
   - Add a route-type or per-route speed input, seeded from real data where it exists:
     - Dedicated-lane BRT (Red, Orange): can plausibly sustain a higher, more
       consistent average speed than the current 20 km/h default — there is no
       directly-published average speed for these lines in the research found, so any
       new constant here is still an assumption, just a route-aware one; it should stay
       clearly documented as an assumption, not implied to be sourced.
     - Mixed-traffic (Blue, Green, all FR feeders): the confirmed FR-4 (19 stops, 45
       min end-to-end), FR-7 (17 stops, 35 min), FR-8 (18 stops, 40 min) journey times
       from Wikipedia's table give a **real, grounded** average pace-per-stop for
       feeder-route simulation, even without knowing the exact km length of each route
       segment — e.g. FR-4 averages ~2.5 minutes per inter-stop hop end-to-end
       (45 min / 18 hops), which is a materially different (slower, more dwell-heavy)
       pace than a flat 20 km/h + 20 s dwell would produce for a similarly-spaced
       route, and is worth calibrating the mixed-traffic default against.
   - This remains a "minimum necessary assumption," per the existing module's own
     documented philosophy — just a better-informed one, not a rewrite of the
     philosophy itself.
2. `simulation.engine`'s interpolation should optionally walk a real `Route.path`
   polyline instead of a straight line between two adjacent stops, when that geometry
   is available. **STATUS: NOT YET DONE — this is Phase 4, not Phase 3.** Phase 3
   only built the geometry-*generation* side (`seeding/route_geometry.py`); the
   description below is still a spec for a next phase, not something to assume is
   already wired up:
   - Additive: `TripSchedule`/`ScheduleStop` would need the relevant route's polyline
     (or pre-computed cumulative-distance-along-path values per stop) made available
     to `compute_position_at`, and the existing straight-line
     `simulation.geo.interpolate_point` call would become "interpolate along the
     polyline segment between this stop's and the next stop's projected position on
     `Route.path`" instead of "interpolate directly between the two stop points."
   - When `Route.path` is `NULL` for a route (true for every route in the live
     database as of this revision — Phase 3's generation script was run live on
     2026-08-17 and works, but no route's full stop sequence is located yet, so no
     real route qualified, see `backend/plan.md`'s Phase 3 handoff and DATA_GAPS.md
     §6 — and will remain true for the four main Metrobus lines and most feeder
     routes even once one qualifies, per DATA_GAPS.md), the existing straight-line
     behavior remains the correct fallback — this is not a breaking change, it's a
     better path taken only when better data exists.
   - This keeps `simulation.engine` a pure, deterministic, DB-free module — the
     polyline itself is loaded by `simulation.trip_builder`/`simulation.provider` (the
     existing DB-adapter layer), exactly as `Route.path`/coordinates are loaded there
     today; `compute_position_at` just receives more/better input, not new
     responsibilities.
3. The import schema (`seeding/import_schema.py`) needs new **optional** dataclasses
   for route geometry and (once/if real data ever exists) trips/stop_times/service
   calendars — see TRANSIT_RESEARCH.md §16 step 1. Nothing about the existing
   `ImportAgency`/`ImportStop`/`ImportRoute`/`ImportRouteStop` shape needs to change;
   this is additive.

## 3. Determining vehicle position between stops (recap + what's new)

Today (unchanged logic, better-calibrated inputs):

1. `simulation.trip_builder.build_trip_for_route` reads a `Route`'s `RouteStop`s in
   order.
2. `simulation.timing.compute_stop_time_offsets` turns that into arrival/departure
   offsets, using (now, ideally) a route-aware speed assumption instead of one global
   constant.
3. `simulation.engine.compute_position_at`, given "elapsed seconds since trip start,"
   finds which `arrival_offset_s`/`departure_offset_s` bracket the elapsed time falls
   into, and either returns a stop position (dwelling) or a linearly interpolated
   position between two stops (en route) — and, once `Route.path` exists for a route,
   "linearly interpolated" becomes "interpolated along the real path segment between
   the two stops' projected points" rather than a straight line between their raw
   coordinates.

## 4. Dwell time at stops

Currently a flat `DEFAULT_DWELL_SECONDS = 20.0` for every intermediate stop on every
route. No real per-stop dwell-time data exists in any source found (unsurprising — this
is operationally granular data even official GTFS feeds often only approximate). No
change recommended here beyond, optionally, distinguishing BRT-station dwell (likely
slightly longer given platform-screen-door boarding, per the Red/Orange Lines'
described automated-turnstile/platform-screen-door stations) from curb-side
mixed-traffic-route dwell — this is a minor, low-confidence refinement, not a
priority.

## 5. Service calendars, trip start/end, route direction

- **Service calendar**: `transit_data.json` records a `daily_default` calendar
  (7 days/week, 06:15–22:00, matching every source's consistent operating-hours claim)
  and a `weekend_special` calendar stub for the two CDA "ST-01"/"ST-02" special trips
  (Sat/Sun only, hourly) named on the transit map PDF — these are not yet attached to
  any route (no stop sequence exists for them), so they have no simulation effect yet.
  No holiday/exception calendar data was found anywhere.
- **Trip start/end**: unchanged from the existing model — a `Trip.scheduled_start_time`
  plus its `StopTime`s define one run. Nothing in the research changes this shape;
  it just changes what informs the offsets.
- **Route direction**: the existing schema models each `Route` as one ordered
  `RouteStop` sequence (implicitly one direction). Every real route researched here is
  a bidirectional corridor (e.g. Red Line runs both Saddar→Pak Secretariat and the
  reverse) — the existing model does not appear to have an explicit "direction" concept
  distinct from "a second `Route` row for the reverse direction," which is a
  reasonable, minimum-viable approach and requires no schema change: model the reverse
  direction of a researched route as a second `Route` row with the stop sequence
  reversed, once/if that's needed for the demo. Not required by anything in this
  research to be done immediately, since the current stop-sequence data is one-
  directional anyway (reconstructed only in the Saddar→Pak Secretariat order the
  source presented it in).

## 6. Multiple simultaneous simulated buses

Already fully supported by the existing architecture (`Trip`/`Vehicle` are independent
rows; `SimulationService.record_all_active_positions` and
`SimulatedVehicleLocationProvider.list_active_positions` already iterate over every
active trip). Nothing in this research changes that. The one relevant addition: once
real headway/frequency data informs how many simultaneous trips *should* plausibly be
running on a given route at once (e.g. Red Line's "every 3–6 minutes" vs. a feeder's
"every 10 minutes" implies a materially different fleet-in-service count for a
realistic-looking demo), a future demo/seed script could use that real headway figure
to decide how many `Trip`s to spin up concurrently per route — this is a seed-data/demo
-script concern, not a `simulation.engine`/`simulation.service` architecture change.

## 7. Delays (future)

Not implemented by the simulator itself now, and should not be — see
MAP_AND_REALTIME_RECOMMENDATIONS.md §E for the full delay/ETA design. In short: a
simulated trip has no "delay" concept (it's definitionally on its own assumed
schedule); delay only becomes meaningful once a real feed exists to compare against.
If a demo ever wants to *simulate* the appearance of a delay for demonstration
purposes, that should be modeled as an explicit, clearly-labeled "delay injection" test
knob on `SimulationService` (e.g. `start_trip(..., delay_offset_s=...)` shifting the
elapsed-time calculation), never as a fabricated real-world delay value presented
without qualification to a user.
