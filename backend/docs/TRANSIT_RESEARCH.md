# TRANSIT_RESEARCH.md — Karwan-e-Khizr Research Package

**Audience:** OpenCode (implementation agent). This document is a research summary, not
an implementation plan — see the final section for the recommended build order.
**Do not re-research the transit system** unless verifying something specific; use
`transit_data.json`, `SOURCES.md`, and `DATA_GAPS.md` alongside this file.

> **UPDATE (this revision):** a follow-up research pass found that CDA publishes
> official, stop-level, GTFS-shaped timetable PDFs for its feeder-route network at
> `https://www.cda.gov.pk/Assets/metro_transit_route/<CODE>_<Forward|Backward>.pdf`,
> indexed at `https://www.cda.gov.pk/cdaTransitMap`. This directly overturns §8's
> original conclusion that no stop-level timetable exists anywhere — it exists for the
> CDA feeder network (not for the four main Metrobus lines, where the original
> conclusion still holds). Four routes (FR-01, FR-04, FR-07, FR-14) now have real,
> officially-sourced stop-level trip data imported into `transit_data.json`. §6 and §8
> below are updated accordingly; DATA_GAPS.md §0 has the full detail.

---

## 1. Project context (recap)

Karwan-e-Khizr is a transit-journey-planning backend for Islamabad–Rawalpindi. The
immediate goal of this research is a **realistic bus simulator**: simulated vehicles
should run on real routes, visiting real stops, at speeds/timings grounded in whatever
real published information exists — not generic fake buses on fake routes. The same
data becomes the scheduled baseline for a future real-time comparison layer.

## 2. Current backend capabilities discovered (repository inspection)

The repository (`backend/`) already implements, in working order:

- **Static transit model**: `Agency` → `Route` (with a nullable PostGIS `LINESTRING`
  `path` column that is **not yet populated or exposed by any API** — see §7) →
  `RouteStop` (ordered, with an optional `distance_along_route_m`) → `Stop`
  (PostGIS `geography(Point)`).
- **Realtime/simulation model**: `Trip` (a single scheduled run of a `Route`, with a
  `status` state machine `scheduled → active → completed/cancelled`) → `StopTime`
  (`arrival_offset_s`/`departure_offset_s`, seconds since `Trip.scheduled_start_time`)
  → `Vehicle` → `VehiclePosition` (append-only history).
- **Simulation engine** (`simulation/engine.py`): a pure, deterministic
  `compute_position_at(schedule, elapsed_s)` function. Given a `TripSchedule` (ordered
  stops + offsets) and elapsed seconds, it returns exactly one position: parked at the
  first stop before departure, **linearly interpolated in raw lat/lon** between
  consecutive stops while en route, dwelling at intermediate stops, and clamped at the
  last stop once complete. This is well-designed and reusable **as-is** — the gap is
  only in what feeds it (see §6).
- **Timing assumption layer** (`simulation/timing.py`): today, `StopTime` offsets are
  **synthesized**, not real: `compute_stop_time_offsets` assumes a flat 20 km/h average
  speed and a flat 20-second dwell at every intermediate stop, using
  `RouteStop.distance_along_route_m` if present, else Haversine straight-line distance
  between stop coordinates. This is explicitly documented in the code as a placeholder
  ("the minimum necessary assumption... do NOT invent a complicated scheduling
  system") and is exactly the layer this research is meant to let OpenCode replace
  with real, per-stop data where it exists.
- **Trip builder / provider / service** (`simulation/trip_builder.py`,
  `simulation/provider.py`, `simulation/service.py`): a clean write path
  (`build_trip_for_route` creates a `Trip` + `StopTime`s from a `Route`'s current
  `RouteStop`s), a clean read path (`SimulatedVehicleLocationProvider`, behind a
  `VehicleLocationProvider` Protocol — explicitly designed so a future
  `RealGpsVehicleLocationProvider` can be swapped in with no caller changes), and a
  control-plane (`SimulationService.start_trip`/`stop_trip`/`record_position`).
- **Routing/journey search** (`routing/`): graph construction, walking connections
  (`WALKING_RADIUS_M` = 400 m), and `fastest`/`fewest_transfers`/`least_walking`
  objectives, already exercised by the seed dataset's deliberate transfer scenarios.
- **Data import** (`seeding/`): a small, source-agnostic `ImportDataset` (agencies,
  stops, routes, route_stops only — **no geometry, no trips/stop_times, no service
  calendar** in the current import schema; see §9) parsed from JSON or CSV, validated,
  then persisted. `insert`/`replace`/`reset` modes keyed by deterministic UUIDs.
- **Realtime API** (`api/transit/realtime/`): read-only `GET /transit/realtime/vehicles`
  and `/vehicles/{id}`, already provider-abstracted.
- **Static transit API** (`api/transit/router.py`): agencies, routes, stops, a route's
  ordered stops, nearby-stops search — but **`Route.path` is explicitly and
  deliberately not serialized yet** (documented in that file's own module docstring as
  "left for whenever the mobile client actually needs to render route paths").
- **Seed dataset** (`backend/data/seed_dataset.py`): a small, deterministic, **already
  loosely-real** demo network — Islamabad Metrobus "blue line" (`BL`, 6 stops:
  Pak Secretariat → Faizabad) and Rawalpindi Metrobus "red line" (`RL`, 9 stops:
  Faizabad → Saddar), plus two invented feeder routes (`F-1`, `F-2`). Its own docstring
  is explicit that these are "hand-picked... geographically plausible... but NOT
  surveyed/GTFS-grade positions." Important: **the seed dataset's route names ("blue
  line"/"red line") do not match the real network's route names** — the real Red Line
  actually is Pak Secretariat↔Saddar in one single corridor, not split across two
  differently-colored routes as the seed models it. This is flagged in §8 and
  DATA_GAPS.md; it does not need to be "fixed" before other work proceeds, but OpenCode
  should not assume the seed dataset already *is* research-grade real data.
- Auth, fares, ticketing/QR, and admin/dev tooling exist and are out of this research's
  scope; they are unaffected by anything recommended here.

**Architectural implication:** nothing here requires touching or replacing the routing
engine or the simulation engine's core interpolation logic. The gaps are entirely
upstream — in what data feeds `RouteStop.distance_along_route_m`, `Route.path`,
`StopTime` offsets, and the import schema that populates them.

## 3. Research methodology

Source-priority order followed (see harm/quality instructions and SOURCES.md for the
full list): (1) official government/operator sources — CDA's own transit-map PDF was
located and fetched directly; (2) Wikipedia's "Rawalpindi–Islamabad Metrobus" article,
which is well-cited to news/official sources for structural facts (opening dates,
lengths, operator names, station *counts*) even though its per-station name lists are
presented as unordered image-alt-text fragments, not a data table; (3) several
SEO/listicle secondary sources (INCPak, rehbar.pk, icons.com.pk, Graana) used only for
cross-checking ordered station-name lists and fares/frequency, never as a sole source
for anything load-bearing; (4) a search for a public GTFS/GeoJSON feed for this system
came back empty — none exists (see DATA_GAPS.md).

No OSM Overpass queries could be executed directly in this research pass (no live
Overpass/API access from this environment) — §11 and MAP_AND_REALTIME_RECOMMENDATIONS.md
specify exactly what OpenCode (or a follow-up research pass with Overpass access)
should query for and how to validate the results.

## 4. Geographic scope

Islamabad + Rawalpindi twin-city corridor only, per the brief. All routes recorded in
`transit_data.json` operate inside this area. No Punjab-wide or national services were
researched or included.

## 5. Operators/services found

- **Punjab Mass Transit Authority (PMTA)** — operates the **Red Line** (the original
  2015 corridor).
- **Capital Development Authority (CDA)** / **Capital Mass Transit Authority (CMTA)** —
  operate the **Orange**, **Blue**, and **Green** Metrobus lines, plus the CDA feeder
  network (`FR-01` through at least `FR-15`, of which only FR-4, FR-7, FR-8 are
  confirmed *operational* by Wikipedia's own table as of its last edit; the rest are
  named on the CDA map PDF with no confirmed operational-status data found).
- No informal/paratransit (wagons, Suzukis, vans) data was pursued — these are
  real and heavily used in the twin cities, but no authoritative route/stop/timing
  source exists for them, and the brief's `10–20 highly reliable routes over 100
  guessed ones` guidance argues against including them without real data.

**System totals (official/Wikipedia table):** 4 Metrobus lines, 83.6 km combined,
listed as 52 stations network-wide (Wikipedia infobox) — note this headline "52" does
not currently reconcile cleanly against the per-line station counts summed (24+7+13+8 =
52, so it *does* reconcile against the official per-line counts, but not against the
named-station lists this research was able to reconstruct — see DATA_GAPS.md).

## 6. Route information

Full structured detail is in `transit_data.json`. Summary:

| Route | Agency | Length | Official stations | Frequency | Dedicated lane | Geometry |
|---|---|---|---|---|---|---|
| Red | PMTA | 22.5 km | 24 | every 3–6 min (06:00–20:00) | Yes | UNKNOWN |
| Orange | CDA/CMTA | 25.6 km | 7 (conflict: some sources say 14) | every 5–10 min | Yes | UNKNOWN |
| Blue | CDA/CMTA | 20 km | 13 | every 6 min | **No** (mixed traffic, Islamabad Expressway) | UNKNOWN |
| Green | CDA/CMTA | 15.5 km | 8 | every 6 min | **No** (mixed traffic, Srinagar Highway) | UNKNOWN |

Only the **Red Line** has a reconstructed, ordered, named stop sequence sourced from
secondary listicles in this research pass (23 names reconstructed against an official
count of 24 — see DATA_GAPS.md). Orange/Blue/Green have confirmed **endpoints and a
partial, unordered name list** only. No stop-level timetable was found for any of
these four lines (§8).

**CDA feeder network — corrected and substantially expanded this revision** (see
DATA_GAPS.md §0 for full detail; sourced to the CDA's own route index page,
superseding this table's earlier, less-authoritative version):

| Route | Long name | Headway | Stop-level timetable imported? |
|---|---|---|---|
| FR-01 | Khanna Pul – NUST Metro Station | 60 min | **Yes** — 26 stops, 16 trips/day |
| FR-04 | PIMS Hospital – Bari Imam | 10 min | **Yes** — 25 stops, 97 trips/day |
| FR-07 | PIMS Hospital – Police Foundation Metro Station | 10 min | **Yes** — 23 stops, 97 trips/day |
| FR-14 | Bara Kahu – Mandi Morh | 15 min | **Yes** — 18 stops, 65 trips/day |
| FR-03A | PIMS Hospital – Saidpur Village | 20 min | Partial (fragment only, not imported) |
| FR-06 | PIMS Hospital – Golra Sharif | 60 min | Partial (fragment only, not imported) |
| FR-09 | Khanna Pul – Golra Morh Metro Station | 15 min | Partial (fragment only, not imported) |
| FRG-1 | PIMS – Barakahu | 5 min | Partial (fragment only, not imported) |
| FR-04A, FR-04B, FR-05, FR-08A, FR-08C, FR-10, FR-11, FR-12, FR-13, FR-14A, FR-15, FRB-01, ST-01, ST-02 | (various — see `transit_data.json`) | various | No — confirmed to exist with a real name/headway/PDF URL; not fetched |

All 22 confirmed route/direction pairs are recorded in `transit_data.json`'s `routes`
array with `confidence: OFFICIAL` name/headway/endpoint data (sourced to the CDA index
page); the four with a fetched timetable additionally have real `trips`/`stop_times`
data. **Every routing/PDF-URL detail needed to fetch the remaining 18 is already in
`transit_data.json` and DATA_GAPS.md §0 — this is a mechanical extraction task, not
further research.**

**Blue/Green Lines run in mixed traffic, not a dedicated lane.** This matters directly
for simulation: an assumed average speed for these two lines should be materially
slower and more variable than for Red/Orange, and any future "predicted vs scheduled"
delay logic should expect larger natural variance on these lines even before real GPS
data exists.

## 7. Stop information

`transit_data.json`'s `stops` array carries 37 stop records. Their coordinate
provenance is **not uniform** and is marked per-record:

- A subset (17 stops) reuse the coordinates already hand-curated in the existing
  repository's `backend/data/seed_dataset.py`, where a seed stop's *key* clearly
  corresponds to a real, confirmed station name (e.g. `saddar`, `faizabad`,
  `pak_secretariat`). These are marked `confidence: APPROXIMATE` and sourced back to
  that file — they were already documented there as "geographically plausible... not
  surveyed."
- The remaining stops (mostly interior Red Line stations not present in the existing
  seed dataset, e.g. Waris Khan, Rehmanabad, 6th Road, Shamsabad, Potohar, Peshawar
  Morr, Chaman, Ibn-e-Sina, Stock Exchange, 7th Avenue, Shaheed-e-Millat) have a
  **confirmed name and route position but NO coordinate** — `latitude`/`longitude` are
  `null`, `confidence: RECONSTRUCTED` or `UNKNOWN`. **No coordinate was invented for
  any of these.**

**Do not blindly reuse the existing seed dataset's coordinates as "real."** They were
already self-described as approximate placeholders by the team that wrote them; this
research does not upgrade their confidence level, it only confirms which of those seed
*names* correspond to real, confirmed stations (vs. seed stops that don't map to any
official name found in this research — e.g. `poly_clinic`, which does not appear in any
official Red Line source consulted here; see DATA_GAPS.md).

## 8. Timetable information

**UPDATED — no longer true as originally stated.** CDA's per-route feeder timetable
PDFs (§0 of DATA_GAPS.md) DO give real, official, stop-level arrival/departure times
for every trip of the service day, for at least the CDA feeder network. Four routes'
full timetables were fetched and imported: **FR-01** (Khanna Pul↔NUST, 26 stops, 16
trips/day @ 60-min headway), **FR-04** (PIMS Hospital→Bari Imam, 25 stops, 97 trips/day
@ 10-min headway), **FR-07** (PIMS Hospital→Police Foundation Metro Station, 23 stops,
97 trips/day @ 10-min headway), **FR-14** (Bara Kahu→Mandi Morh, 18 stops confirmed, 65
trips/day @ 15-min headway). Each is stored in `transit_data.json`'s `trips` array as
one real canonical stop-time pattern (verified to repeat exactly, time-shifted by the
headway, across every trip inspected) plus the service parameters needed to regenerate
every trip of the day (`headway_min`, `total_trips_per_day`, `first_trip_start`,
`last_trip_start`) — this is genuinely the "07:10 → Stop A, 07:17 → Stop B" shape the
brief asked for, sourced and provenance-tagged, for these four routes.

18 more CDA feeder route/direction pairs are confirmed to exist (with official names,
endpoints, and headways, from the CDA index page) but their own stop-level PDFs were
not fetched in this pass — fetching them is a mechanical follow-up (the URL pattern and
full route list are in DATA_GAPS.md §0 and SOURCES.md §1.4), not a research gap.

**This does not extend to the four main Metrobus lines** (Red, Orange, Blue, Green).
The rest of this section (as originally written) still applies to those:

Every source — including the CDA's own graphic transit map PDF — expresses service
level for the Metrobus lines only as:

- Overall operating hours (06:15–22:00, consistent across all sources), and
- A per-route/per-line **headway/frequency** (e.g. "every 3–6 minutes" for Red Line
  peak; "every 10 minutes" for feeders), and, for three feeder routes, an **end-to-end
  journey time** (FR-4: 45 min; FR-7: 35 min; FR-8: 40 min — these are directly useful
  as a sanity check on an assumed average speed, see SIMULATION_DATA_SPEC.md).

This means: **per the task's instruction, individual stop-level times must not be
fabricated.** The simulator cannot currently be driven by a real published timetable
in the "07:10 → Stop A, 07:17 → Stop B" sense the brief describes as the target shape.
It CAN be driven, more realistically than today, by:

1. A real ordered stop sequence (available for the Red Line now; others need more
   digitization work — see §10, DATA_GAPS.md), plus
2. A real route-specific average-speed assumption **grounded in whatever real
   distance/journey-time data exists** (e.g. Red Line's 22.5 km / published frequency;
   FR-4/7/8's confirmed end-to-end times), rather than one flat 20 km/h constant applied
   to every route regardless of dedicated-lane status — see SIMULATION_DATA_SPEC.md §3.
3. A weekend-only special-trip calendar for the two CDA "ST-01"/"ST-02" services named
   on the transit map PDF (hourly, Sat/Sun only) — recorded as a service-calendar stub
   in `transit_data.json`, not yet attached to a route, since no stop sequence exists
   for them either.

The **CDA Metro App** (`com.kentkart.cdamobile`) and a July-2026 CDA announcement
describe live GPS tracking and "estimated arrival/departure times" being rolled out
through Google Maps integration (see SOURCES.md) — this is the eventual real-time
source the architecture should be ready to plug in later (§13), not something usable
today (no public API was found, and none should be assumed to exist without a
confirmed developer-facing endpoint).

## 9. Geometry information

**No official route polyline/shapefile/GeoJSON was found for any route — this
finding is unchanged by the follow-up pass.** The CDA per-route timetable PDFs (§8)
give stop **names and times only**; they do not contain coordinates or geometry of any
kind. This is worth stating explicitly since it would be easy to assume otherwise given
how rich the timetable data is — checked directly, and confirmed absent. The CDA
transit map PDF is a graphic map (illustrator-style layout with a legend), not a GIS
export — text extraction from it returns an unordered bag of route codes and stop-name
labels, not coordinates or a path. No GTFS feed exists (confirmed by search; see
DATA_GAPS.md). No public transit-specific GeoJSON/shapefile repository for this system
was found on GitHub or elsewhere.

**Recommended geometry strategy** (detailed further in
MAP_AND_REALTIME_RECOMMENDATIONS.md and SIMULATION_DATA_SPEC.md):

1. For routes with a confirmed ordered stop sequence and coordinates (currently: a
   subset of Red Line stops), road-following geometry can be reconstructed via an
   OSM-based routing engine (e.g. OSRM/Valhalla against an Islamabad/Rawalpindi OSM
   extract, or the free OSRM demo server for prototyping only — not for production
   load) snapped through each stop in sequence. This produces a `RECONSTRUCTED`
   (not `OFFICIAL`) geometry — accurate to "follows real roads" but not to "is the
   bus's actual lane/alignment," which matters especially for the Red/Orange Lines'
   *dedicated, often elevated or trenched* busway that does not run on the same
   alignment as general-traffic roads at every point.
2. For the dedicated-lane BRT corridors (Red, Orange) specifically, OSM likely already
   contains the physical busway as a distinct way/relation (BRT infrastructure is
   commonly mapped in OSM even where GTFS is not published) — this should be checked
   directly (via Overpass, `highway=busway` / `bus=designated` tags, or a `route=bus`
   relation already tagged for these lines) before falling back to road-snapping
   through stops, since a real physical-alignment geometry is a strictly better input
   to the simulator than a road-snapped reconstruction.
3. Until either exists, `Route.path` should remain `NULL` for a route rather than
   populated with a straight-line or fabricated polyline — the existing simulator's
   interpolation degrades gracefully (straight-line between consecutive stops) when
   `Route.path` is absent, and that is a more honest state than a geometry field that
   looks authoritative but isn't.

## 10. Simulation implications

See SIMULATION_DATA_SPEC.md for the full mapping. Headline points:

- The existing `simulation.engine.compute_position_at` needs **no changes** to consume
  either (a) better `StopTime` offsets or (b) real route geometry for interpolation —
  it already interpolates between two points; today those two points are always
  "the two adjacent stops," and %-along-segment interpolation against a real polyline
  is a natural, additive extension (walk the polyline instead of a straight line
  between stop coordinates), not a rewrite.
- `simulation.timing.compute_stop_time_offsets`'s flat 20 km/h / 20 s-dwell assumption
  should become **route-aware**: dedicated-lane BRT routes (Red, Orange) plausibly
  travel faster and more consistently than mixed-traffic routes (Blue, Green, all
  feeders) — the confirmed FR-4/7/8 end-to-end journey times give a concrete,
  real-data-grounded average speed to calibrate feeder-route assumptions against,
  instead of one constant for the whole network.
- The current import schema (`seeding/import_schema.py`) has **no field for route
  geometry, trips, stop_times, or a service calendar** — only agencies/stops/routes/
  route_stops. This is the concrete gap blocking "import the researched dataset" as
  step 2 of the recommended order (§14): the import schema needs extending before
  `transit_data.json`'s fuller structure (trips, stop_times, calendars, transfers) can
  be loaded, even though the *current* research dataset has no real trips/stop_times to
  import yet (they're legitimately empty pending real per-stop timetable data, per §8).

## 11. Future realtime implications

- No GTFS-Realtime feed, and no confirmed public developer API, exists for this
  network today. The CDA's July-2026 "real-time tracking... integrated into the new
  CDA Mobile App" announcement (SOURCES.md) is the one concrete signal that official
  realtime data may become available later, but it describes an in-app Google Maps
  integration, not a documented external API — nothing should be built assuming a
  specific endpoint shape from that announcement.
- The existing `VehicleLocationProvider` Protocol (`simulation/provider.py`) is already
  exactly the right shape to receive a future real provider with no caller-side
  changes — this research does not recommend changing that interface.
- When/if a real feed appears, delay computation is `actual/predicted − scheduled`,
  where "scheduled" must come from real timetable data if it exists by then, or
  otherwise from the same route-aware simulated-schedule assumption described above,
  clearly labeled as an assumption rather than a real schedule, in the API response
  to the frontend. See MAP_AND_REALTIME_RECOMMENDATIONS.md §E.

## 12. Mapping implications

Summarized in full in MAP_AND_REALTIME_RECOMMENDATIONS.md. The existing project
`README.md` (§17) already made and documented a map-technology decision — **MapLibre
Native + OpenStreetMap-derived vector tiles**, specifically to avoid a paid-API/
licensing dependency for a hackathon-scope, possibly-public deployment. This research
did not find any reason to revisit that decision; it is reaffirmed with supporting
detail in the recommendations doc, particularly around what the *backend* needs to
expose (currently: stop lat/lon only; route polylines are not yet serialized, see §2)
to make that frontend choice usable.

## 13. Data-quality / confidence assessment

Roughly, by category:

| Category | Confidence | Basis |
|---|---|---|
| Route existence, names, operators, opening dates | VERIFIED | Wikipedia, well-cited to news sources |
| Route lengths, official station *counts*, frequencies | VERIFIED | Wikipedia's own infobox/route table |
| Red Line ordered stop *names* | RECONSTRUCTED | Cross-checked secondary source, not official |
| Red Line stop *coordinates* | APPROXIMATE (where present) / UNKNOWN (rest) | Reused repo seed data / not established |
| Orange/Blue/Green ordered stop sequence | UNKNOWN | Only partial unordered name lists found |
| Any stop-level scheduled time | UNKNOWN — genuinely does not exist in any source found | — |
| Any route geometry/polyline | UNKNOWN — must be reconstructed, not sourced | — |
| CDA feeder routes FR-01..FR-15 (beyond FR-4/7/8) | OFFICIAL (existence/endpoints only) | CDA Transit Map PDF |

## 14. Unresolved conflicts

See DATA_GAPS.md for the full, explicit list. The three most implementation-relevant:

1. **Red Line station count**: 24 (official, multiple sources) vs. 23 names
   reconstructable from the one ordered secondary list found.
2. **Orange Line station count**: 7 (Wikipedia's own summary table) vs. 14 (several
   independent listicles).
3. **"Faizabad" vs. "Faiz Ahmed Faiz"**: two distinct real Red Line stations with
   confusingly similar names — several secondary sources conflate or misattribute
   which one is the Orange Line interchange. This research resolves it as: **Faiz
   Ahmed Faiz is the interchange**, per Wikipedia's article body text, and the two are
   recorded as separate stops in `transit_data.json`. Any future source that
   contradicts this should be treated as a genuine open question, not silently
   overridden.

## 15. Implementation recommendations (non-exhaustive; see §16 for order)

- Extend the import schema to carry (all optional/nullable): `route.path` (WKT or
  GeoJSON LineString), `trips`, `stop_times`, and a minimal `service_calendar` —
  before attempting to import anything beyond the current agencies/stops/routes/
  route_stops shape.
- Expose `Route.path` (once populated) via the transit API as GeoJSON, additive to the
  existing `Coordinates`-based `StopRead`/`RouteDetail` schemas — do not replace the
  existing lat/lng point representation, which is still right for stop markers.
- Make `simulation.timing`'s speed/dwell constants a per-route (or per-route-type:
  dedicated-lane vs. mixed-traffic) parameter instead of one global constant, and seed
  the mixed-traffic assumption from the FR-4/7/8 confirmed journey times.
- Do not attempt to populate `StopTime` with fabricated per-stop times; keep the
  existing offset-computation approach for routes without real data, just make its
  inputs more realistic (real stop sequence + route-aware speed) rather than
  pretending a real timetable exists. **For FR-01/04/07/14, real stop-level offsets
  now exist — import them directly rather than computing assumed ones (see
  SIMULATION_DATA_SPEC.md, updated).**
- Fetch the remaining 18 CDA feeder routes' timetable PDFs (URL pattern and full list
  in DATA_GAPS.md §0) before assuming their stop sequences are unavailable — this is
  the highest-value, lowest-effort next step in the whole package, since the source is
  already known, public, and confirmed to work.
- Treat `Route.path` as legitimately `NULL` for any route until real/reconstructed
  geometry exists for it — the simulator already degrades gracefully to straight-line
  interpolation in that case.

## 16. RECOMMENDED IMPLEMENTATION ORDER

Adjusted from the brief's example order based on what this inspection actually found:

1. **Extend the import schema** (`seeding/import_schema.py`, `parsers.py`,
   `validation.py`, `importer.py`) to accept optional route geometry (WKT/GeoJSON
   LineString), and optional `trips`/`stop_times`/`service_calendar` records — additive,
   nullable fields only; existing agencies/stops/routes/route_stops import behavior
   must not change. **This step just got more valuable**: `transit_data.json` now
   contains real `trips`/`stop_times` data (FR-01/04/07/14) that needs exactly this
   schema extension to import, not just a hypothetical future need.
2. **Import the researched static dataset** (`transit_data.json`'s operators, stops,
   routes, route_stops, trips, stop_times, transfers) via that extended importer, in
   `replace` mode against a scratch/dev database, distinct from (not overwriting) the
   existing hackathon seed dataset unless/until a decision is made to replace it. For
   FR-01/04/07/14, this means generating the full day's real trips by repeating each
   route's canonical stop-time pattern every `headway_min` from `first_trip_start` to
   `last_trip_start` (`total_trips_per_day` trips total) — a direct, mechanical
   expansion, not an assumption (see SIMULATION_DATA_SPEC.md).
2a. **(New, optional, high-value) Fetch the remaining 18 CDA feeder routes' PDFs**
    before or alongside step 2 — same URL pattern, same extraction approach, already
    proven to work for 4 routes. Doing this now, before building on top of the current
    4-route dataset, avoids re-doing the import-schema/simulation-integration work
    twice.
3. **Reconstruct road-following route geometry** for at least the Red Line (the one
   route with a full ordered stop sequence) via an OSM-based approach (§9), and store
   it in `Route.path`. Leave `Route.path` `NULL` for every other route until their stop
   sequences/geometry exist.
4. **Expose geographic data via the transit API**: serialize `Route.path` as GeoJSON
   (additive endpoint or field), review the nearby-stops/route-detail endpoints for
   what a map client needs (see MAP_AND_REALTIME_RECOMMENDATIONS.md §B).
5. **Make simulation timing route-aware**: replace the single global
   `SIMULATED_VEHICLE_SPEED_KMH`/`DEFAULT_DWELL_SECONDS` with per-route (or
   per-route-type) values, calibrated against the real frequency/journey-time data
   found in this research.
6. **Upgrade simulator interpolation to walk `Route.path`** (when present) instead of
   a straight line between adjacent stops, for the routes where geometry now exists;
   fall back to the existing straight-line behavior otherwise — this is additive to
   `simulation.engine`, not a rewrite of it.
7. **Expose simulated vehicles + route geometry + stops together** in whatever shape
   the frontend map layer needs (§B of the recommendations doc).
8. **Add a realtime-provider abstraction placeholder** — no implementation, just
   confirm `VehicleLocationProvider` remains the seam, and design the
   scheduled-vs-real comparison data shape now so it doesn't require an API breaking
   change later (§13 of this document, §E of the recommendations doc).
9. **Add scheduled-vs-real comparison + delay/ETA computation** once (8) exists and a
   real feed is actually available — do not build this against fabricated "real" data.
10. **Frontend integration** — after the above, since none of it requires frontend
    changes to be useful for the simulator/demo in the interim.

Do not implement any of this yet — research and specification only, per the brief.
