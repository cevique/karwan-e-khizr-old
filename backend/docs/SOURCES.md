# SOURCES.md

Every source consulted for this research pass, in the order the source-priority
hierarchy in the task ranks them. "Dataset elements depending on it" references
`transit_data.json` record types.

---

> **UPDATE (this revision):** §1.4–§1.6 below are new primary sources found in a
> follow-up research pass. They are the most authoritative sources in this entire
> package — official, structured, stop-level, machine-extractable data — and should be
> treated as higher-priority than §1.1–§1.3 wherever they overlap.

## 1. Official government / operator sources

### 1.1 CDA Transit Map of Islamabad (PDF)
- **Title:** Transit Map of Islamabad (Network Design)
- **Publisher:** Capital Development Authority (CDA)
- **URL:** https://www.cda.gov.pk/Assets/pdf/Transit-Map-Islamabad-V-06.pdf
- **Date/version:** "V-06" (no explicit publish date on the document itself; fetched 2026-08-16)
- **Source type:** Official government PDF (graphic transit map, not a data table)
- **Information extracted:** Full list of CDA feeder route codes (`FR-01`..`FR-15`) with
  text descriptions of each route's endpoints/via-streets; the two Saturday/Sunday-only
  "special trip" services (ST-01, ST-02) with their hourly frequency; the
  "Diplomatic Enclave Shuttle Service" (Mon–Fri, every 2–5 min); an unordered set of
  ~150+ stop-name labels scattered across the map; legend distinguishing Metro Station,
  BRT Route, Transfer Station, Combined Stop, Future Routes.
- **Reliability:** High (official primary source) for what it contains.
- **Currentness:** Unknown exact publish date; referenced as "V-06" suggesting at least
  6 revisions; treated as reasonably current but not dated.
- **Limitation:** This is a graphic/illustrated map (PDF text extraction yields
  jumbled/unordered label text, not a stops-per-route data table). No coordinates, no
  stop sequence, no per-stop timing extractable from this document as delivered.
- **Dataset elements depending on it:** `routes` (the `fr_pdf_*` stub entries),
  `service_calendars.weekend_special`, general stop-name vocabulary cross-referenced
  elsewhere.

### 1.2 CDA Metro App (official app listing)
- **Title:** CDA Metro App — Google Play listing
- **Publisher:** Capital Development Authority (via Google Play; developer identity on
  the listing corresponds to a CDA-branded transit app, ticketing vendor KentKart)
- **URL:** https://play.google.com/store/apps/details?id=com.kentkart.cdamobile&hl=en_US
- **Date:** Listing observed January 6, 2026 (per search snapshot metadata)
- **Source type:** Official app store listing / product description
- **Information extracted:** Confirms the existence of an official real-time bus
  arrival / trip-planning app ("Routes: real-time bus arrivals... stop-by-stop
  navigation... nearest buses to your current location").
- **Reliability:** High for "this app/capability exists"; the listing text is marketing
  copy, not a technical/API spec.
- **Currentness:** Current as of the observed date.
- **Dataset elements depending on it:** none directly (informs
  MAP_AND_REALTIME_RECOMMENDATIONS.md §E only — no API contract was found or assumed).

### 1.3 CDA real-time tracking announcement (secondary reporting on an official rollout)
- **Title:** "CDA Real-Time Metro & Electric Bus Tracking in Islamabad & Rawalpindi"
- **Publisher:** ncf.org.pk (reporting on a CDA announcement — not CDA's own site)
- **URL:** https://ncf.org.pk/cda-introduces-real-time-tracking-for-metro-and-electric-buses/
- **Date:** Observed July 3, 2026
- **Source type:** Secondary reporting on an official government initiative
- **Information extracted:** CDA has launched (or announced) live bus-location tracking
  "via Google Maps, fully integrated into the new CDA Mobile App" — live locations,
  routes, stops, arrival/departure estimates, trip planning.
- **Reliability:** Medium (secondary source describing an official action; not verified
  against a CDA press release directly in this pass).
- **Currentness:** Recent (within the current knowledge window).
- **Dataset elements depending on it:** none — informational only, for
  MAP_AND_REALTIME_RECOMMENDATIONS.md §E ("future realtime integration").

### 1.4 CDA Transit Map — Route Details index page
- **Title:** "Transit Map of Islamabad" / "CDA Transit Map - Route Details" (HTML table)
- **Publisher:** Capital Development Authority (CDA)
- **URL:** https://www.cda.gov.pk/cdaTransitMap
- **Date:** Fetched 2026-08-16; page copyright footer reads "Copyright © 2024"
- **Source type:** Official government web page — a structured HTML table, not a
  graphic PDF (unlike §1.1), listing every CDA feeder/special route with its route
  number, full name, direction pair, headway, and a direct link to that
  route/direction's own stop-level timetable PDF.
- **Information extracted:** The authoritative list of 22 route/direction pairs
  (FR-01, FR-03A, FR-04, FR-04A, FR-04B, FR-05, FR-06, FR-07, FR-08A, FR-08C, FR-09,
  FR-10, FR-11, FR-12, FR-13, FR-14, FR-14A, FR-15, FRB-01, FRG-1, ST-01, ST-02) with
  official names and headways, and the URL pattern for each route's own PDF
  (`https://www.cda.gov.pk/Assets/metro_transit_route/<CODE>_<Forward|Backward>.pdf`).
  This superseded and corrected several route-name/endpoint guesses made in the
  original research pass from the graphic PDF alone (§1.1) — see DATA_GAPS.md §3.5.
- **Reliability:** High (official, structured, primary source).
- **Currentness:** Recent; supersedes the static V-06/V-07/V-08 graphic PDF snapshots
  for route-list purposes.
- **Dataset elements depending on it:** `routes` (all 22 `fr_*`/`frb_*`/`frg_*`/`st_*`
  entries — names, headways, endpoints, PDF URLs).

### 1.5 CDA official per-route stop-level timetable PDFs (`metro_transit_route/`)
- **Title:** Individual route/direction timetable documents (e.g. "FR-01_Backward.pdf")
- **Publisher:** Capital Development Authority (CDA)
- **URLs (fetched in full this pass):**
  - https://www.cda.gov.pk/Assets/metro_transit_route/FR-01_Backward.pdf
  - https://www.cda.gov.pk/Assets/metro_transit_route/FR-04_Forward.pdf
  - https://www.cda.gov.pk/Assets/metro_transit_route/FR-07_Forward.pdf
  - https://www.cda.gov.pk/Assets/metro_transit_route/FR-14_Forward.pdf
- **URLs (partially seen via search snippets only, not fully fetched/verified — see
  DATA_GAPS.md §0):**
  - https://www.cda.gov.pk/Assets/metro_transit_route/FR-03A_Forward.pdf
  - https://www.cda.gov.pk/Assets/metro_transit_route/FR-06_Forward.pdf
  - https://www.cda.gov.pk/Assets/metro_transit_route/FR-09_Forward.pdf
  - https://www.cda.gov.pk/Assets/metro_transit_route/FRG-1_Backward.pdf
  - https://www.cda.gov.pk/Assets/metro_transit_route/FR-08A_Forward.pdf (timing
    pattern only, no stop names captured)
  - https://www.cda.gov.pk/Assets/metro_transit_route/FR-08C_Forward.pdf (timing
    pattern only, no stop names captured)
- **URLs confirmed to exist (from §1.4's index) but not fetched at all in this pass:**
  FR-03A/FR-04A/FR-04B/FR-05/FR-06/FR-08A/FR-08C/FR-09/FR-10/FR-11/FR-12/FR-13/
  FR-14A/FR-15/FRB-01/FRG-1/ST-01/ST-02, each with both a `_Forward.pdf` and
  `_Backward.pdf` variant.
- **Date:** No publish date printed on the documents themselves; fetched 2026-08-16.
- **Source type:** Official, structured, machine-extractable route/trip/stop-time
  documents — functionally a GTFS-style stop-time table (Route ID, Short Name, Long
  Name, Direction, Total Trips, Average Headway, then per-trip Trip ID/Start Time
  followed by a `stop_name` / `arrival_time` / `departure_time` table) rendered as PDF.
- **Information extracted:** For the four fully-fetched routes — complete ordered
  stop lists with real arrival/departure times for every trip of the service day,
  confirmed to be exact time-shifted repeats of one canonical pattern by the printed
  headway. See DATA_GAPS.md §0 for full detail and TRANSIT_RESEARCH.md §8 (updated)
  for how this feeds the simulator.
- **Reliability:** Very high (official, primary, structured — the single best source
  in this entire research package).
- **Currentness:** Unknown exact publish/last-updated date; treated as current absent
  evidence otherwise.
- **Limitation (important, per the task's explicit instruction to check this):** these
  PDFs give **stop names and times only** — no stop coordinates (latitude/longitude)
  and no route geometry/polyline appear anywhere in the extracted content. Do not infer
  otherwise.
- **Dataset elements depending on it:** `stops` (all `cda_*`-keyed stops, name/sequence
  OFFICIAL, coordinates explicitly null), `trips` (4 `CANONICAL_PATTERN` records with
  real stop_times).

### 1.6 Daily Times — "CDA launches 13 feeder electric bus routes, paving way for greener capital"
- **Publisher:** Daily Times (Pakistani English-language newspaper), reporting on a
  CDA announcement
- **URL:** https://dailytimes.com.pk/1276977/cda-launches-13-feeder-electric-bus-routes-paving-way-for-greener-capital/
- **Date:** March 19, 2025
- **Source type:** Secondary news reporting on an official government action/statement
- **Information extracted:** A "via" corridor description for most operational feeder
  routes (e.g. "FR-04, (PIMS to Bari Imam to QAU via G-6, G-7 & Abpara)"), corroborating
  §1.4/§1.5's route list. Introduces two new minor, unresolved conflicts with the CDA
  index page (§1.4) on FR-11's and FR-15's stated endpoints — see DATA_GAPS.md §0.
- **Reliability:** Medium-high (established newspaper, reporting on an official
  announcement, largely corroborated by the primary sources above).
- **Currentness:** From March 2025; treated as reasonably current for route-existence
  purposes, though headway/timetable specifics should be trusted from §1.4/§1.5
  instead where they overlap.
- **Dataset elements depending on it:** supplementary `notes` text on several feeder
  `routes` entries (via-corridor descriptions only, not stop sequences).

---

## 2. Encyclopedic / well-cited secondary source

### 2.1 Wikipedia — "Rawalpindi–Islamabad Metrobus"
- **Publisher:** Wikipedia contributors
- **URL:** https://en.wikipedia.org/wiki/Rawalpindi%E2%80%93Islamabad_Metrobus
- **Date:** Article last observed August 2026 (per fetch); individual facts cited to
  dated news sources (Dawn, The News, Express Tribune, ProPakistani, etc.) spanning
  2014–2024, listed in the article's own reference list.
- **Source type:** Encyclopedic secondary source, heavily cross-cited to news reporting
  on official government/operator actions.
- **Information extracted:**
  - System totals: 4 routes, 83.6 km combined, 52 stations network-wide, 99 vehicles,
    began service 2015-06-04.
  - Per-line table: Red (22.5 km, 24 stations, every 3–6 min daytime, PMTA+CDA
    operator), Orange (25.6 km, 7 stations, every 10 min, CDA), Blue (20 km, 13
    stations, every 6 min, shared/mixed traffic), Green (15.5 km, 8 stations, every 6
    min, shared/mixed traffic, journey time "one hour").
  - Feeder-route table: FR-4 (PIMS Gate–Bari Imam, 19 stations, every 10 min, 45 min
    journey, opened 2024-07-05), FR-7 (PIMS Gate–NUST Station, 17 stations, every 10
    min, 35 min journey, opened 2024-07-05), FR-8 (PIMS Gate–Taramari Chowk, 18
    stations, every 10 min, 40 min journey, opened 2024-12-25).
  - Narrative history: Red Line construction/cost (~Rs. 44.31 billion), Orange Line
    delay history, creation of CMTA, NUST's 13-feeder-route feasibility study,
    fleet/vehicle-import history, flooding/structural-crack incidents, financial-loss
    controversy.
  - An infobox image's alt-text/caption fragments listing (unordered) many station
    names across all four lines — used only as a cross-check vocabulary, not as an
    ordered sequence (the fragments interleave route labels and station names without
    reliable positional meaning once extracted as plain text).
- **Reliability:** High for structural facts (cited to specific news reports); **low**
  for the unordered station-name image-fragment text specifically — flagged as such
  everywhere it's used.
- **Currentness:** Current; article reflects events through at least December 2024
  and was live/current as of this research pass.
- **Dataset elements depending on it:** `routes` (red_line, orange_line, blue_line,
  green_line, fr_04, fr_07, fr_08 — all structural fields), `transfers`
  (Red↔Orange interchange), station-name cross-check for `stops`.

---

## 3. Secondary sources used only for cross-checking / fill-in

### 3.1 rehbar.pk — "Rawalpindi Metro Bus Route & Stations List"
- **URL:** https://rehbar.pk/info/rawalpindi-metro-bus-route-and-stations-list/
- **Publisher:** Rehbar.pk (Pakistani local-business/directory site, not a transit
  authority)
- **Date:** Published/modified June 17–18, 2026
- **Source type:** Reputable-effort secondary source (SEO content, not an operator or
  news outlet — used cautiously)
- **Information extracted:** The **only** fully ordered, numbered (1–23), south-to-north
  station table found for the Red Line, with each stop's approximate area/landmark
  and elevated/at-grade/trench track structure. Also repeats fare/frequency/operating-
  hours claims consistent with other sources.
- **Reliability:** Medium — internally consistent and plausible, matches Wikipedia's
  station-name vocabulary closely, but is not an operator or news source and contains
  at least one internal inconsistency (see DATA_GAPS.md: claims "24 operational
  stations" in prose but its own table lists 23 rows). Some claims elsewhere on the
  page (e.g. "12-meter articulated Volvo buses," "Punjab Mass Transit Authority (PMA)")
  use imprecise/possibly incorrect naming compared to Wikipedia's more carefully
  sourced "18-meter articulated buses" and "Punjab Masstransit Authority (PMTA)" —
  not relied upon for those specific claims.
- **Currentness:** Recent (2026).
- **Dataset elements depending on it:** `stops` (Red Line ordered names — key
  reconstruction input), `route_stops` (Red Line sequence).

### 3.2 INCPak — "Islamabad Metro Bus Routes 2026: Map, Stations, Timings, and Fares"
- **URL:** https://www.incpak.com/info/islamabad-metro-bus-routes/
- **Date:** March 11, 2026
- **Source type:** Pakistani news/lifestyle outlet, secondary
- **Information extracted:** Fare figures (Red Line Rs. 30; CDA routes Rs. 100 as of
  June 2025 update; T-Cash card Rs. 130 issuance), operating hours (6:15 AM–10:00 PM),
  frequency ranges by line, claim of "14 stations" for the Orange Line (**conflicts**
  with Wikipedia's table of 7 — see DATA_GAPS.md).
- **Reliability:** Medium.
- **Currentness:** Recent (2026), explicitly dated fare updates.
- **Dataset elements depending on it:** cross-check only for fares/frequency (not
  included as authoritative fare data in `transit_data.json`, which does not model
  fares — that's the existing `Fare`/ticketing subsystem's domain, out of this
  research's scope).

### 3.3 icons.com.pk — "Rawalpindi Islamabad Metro bus Route | Timings | Stops [2026]"
- **URL:** https://icons.com.pk/rawalpindi-islamabad-metrobus
- **Date:** June 3, 2026
- **Source type:** Secondary listicle
- **Information extracted:** Repeats the "Line 1 / Line 2" framing (an informal naming
  not used elsewhere) for Red Line / Orange Line-as-airport-shuttle; claims Orange Line
  has 14 stations (same conflicting figure as INCPak); fare ~PKR 40 (conflicts mildly
  with the Rs. 30 figure elsewhere — likely a rounding/generalization, not treated as
  authoritative).
- **Reliability:** Low–medium; used only to confirm the *pattern* of the 7-vs-14
  Orange Line conflict appearing independently in more than one secondary source
  (making it a real, unresolved discrepancy rather than a single source's typo).
- **Dataset elements depending on it:** none directly; informs DATA_GAPS.md only.

### 3.4 Graana.com — "Islamabad and Rawalpindi Metro Bus Routes"
- **URL:** https://www.graana.com/blog/islamabad-and-rawalpindi-metro-bus-routes/
- **Date:** April 16, 2024
- **Source type:** Pakistani real-estate company's content-marketing blog, secondary
- **Information extracted:** Corroborates the 24-station, 23 km, Pak Secretariat↔Saddar
  description of Line 1, and describes Line 2 as a ~27 km Kashmir Highway corridor
  parallel to Srinagar Highway ending at the new airport (a materially different
  description of "Line 2" than the Orange Line's Wikipedia-sourced routing —
  see DATA_GAPS.md, this may describe a *different, later-built* corridor or be
  conflating Orange/Blue/Green).
- **Reliability:** Low–medium; used only as one more data point for the station-count
  conflicts, not as a primary input to any `transit_data.json` record.
- **Dataset elements depending on it:** none directly.

### 3.5 metro-status.com — FAQ / Red Metro pages
- **URLs:** https://metro-status.com/faq/, https://metro-status.com/red-metro-route/
- **Source type:** Apparent live-status/tracking fan/aggregator site, secondary
- **Information extracted:** Corroborates 24-station, 22.5 km, Pak Secretariat↔Saddar
  figure for Red Line; describes a "real-time tracking dashboard" that is this site's
  own unofficial product, not an official CDA/PMTA feed — **not to be confused with**
  the official CDA app/tracking effort in §1.2/§1.3.
- **Reliability:** Low as a primary source (unofficial third-party site); used only to
  confirm the 24-station figure appears consistently.
- **Dataset elements depending on it:** none directly.

---

## 4. Searches that came back empty (documented per DATA_GAPS.md instruction)

- **GTFS/GTFS-Realtime feed for Rawalpindi/Islamabad**: no public feed found on
  GitHub, MobilityData's `awesome-transit` list, OpenMobilityData, or general web
  search. (The CDA per-route PDFs in §1.5 are GTFS-shaped in content but are not an
  actual GTFS feed/format — they're individual PDFs, not a `stops.txt`/`stop_times.txt`
  dataset.)
- **Official stop-level timetable PDF**: **found in a follow-up pass — see §1.5.** The
  original pass's conclusion that no such document exists was **incorrect**; it existed
  publicly at a discoverable, official URL the whole time and was simply not found by
  the original pass's search queries. This does NOT extend to the four main Metrobus
  lines (Red/Orange/Blue/Green) — no stop-level timetable was found for those in either
  pass; only the CDA feeder network has one.
- **OpenStreetMap route relation data**: still not queried directly in this pass (no
  live Overpass access in this environment) — this is a concrete follow-up action, not
  a "does not exist" finding. See MAP_AND_REALTIME_RECOMMENDATIONS.md §A for exactly
  what to query.

---

## 4a. Tooling used to derive (not source) route geometry — added this revision

### 4a.1 OSRM public routing server
- **Title:** OSRM (Open Source Routing Machine) demo server
- **Publisher:** Project OSRM (community project; the demo server is a free, unauthenticated
  public instance, not an official transit data source)
- **URL:** https://router.project-osrm.org (accessed via `seeding/route_geometry.py`'s
  `OSRMRouteGeometryProvider`; reached live from a Docker-PostGIS environment on
  2026-08-17 and verified to return valid driving-profile polylines for real
  Islamabad/Rawalpindi stop coordinates)
- **Source type:** Third-party routing engine — this is a **tool**, not a transit-data
  source. It is listed here only because it's now part of the data lineage for any
  `Route.path` value that ends up `geometry_source: "OSRM"` — see `backend/plan.md`
  Phase 3.
- **Information extracted:** Nothing transit-specific. Given an ordered list of stop
  coordinates, it returns a road-following driving-profile polyline plus per-leg
  distances. It has no knowledge of, and does not represent, the real bus routes'
  actual lane/alignment (see MAP_AND_REALTIME_RECOMMENDATIONS.md §A.2) — it just finds
  a plausible driving path between points on the general road network.
- **Reliability:** Not applicable in the usual sense — it's not asserting a transit
  fact, it's computing a road path. Its output quality depends entirely on OSM's own
  road-network completeness/accuracy for Islamabad/Rawalpindi, which was not
  separately audited.
- **Currentness:** Not applicable (a live routing service, not a dated document).
- **Limitation (explicit, since this is a very different kind of source from
  everything else in this file):** the free public demo server has no SLA, may be
  rate-limited or slow, and is explicitly documented (in
  `seeding/route_geometry.py` and MAP_AND_REALTIME_RECOMMENDATIONS.md §A.1) as
  appropriate only for a one-time, offline, build-time enrichment script — not for
  any runtime/per-request use.
- **Dataset elements depending on it:** none yet in `transit_data.json` itself (which
  remains a static research artifact); this is a live-database-only dependency, tracked
  in `backend/plan.md`'s Phase 3 handoff, not in this file's dataset.

## 5. Repository (primary source for architecture facts, not transit facts)

- **Karwan-e-Khizr backend repository** (`karwan-e-khizr-main.zip`, as provided).
  Used throughout TRANSIT_RESEARCH.md, DATA_GAPS.md, and SIMULATION_DATA_SPEC.md as
  the authoritative description of the *existing system*, via direct code/README
  inspection (not a web source). Key files referenced: `backend/README.md` (via the
  top-level `README.md`), `backend/data/seed_dataset.py`, `backend/data/README.md`,
  `backend/db/models/*.py`, `backend/simulation/*.py`, `backend/seeding/*.py`,
  `backend/api/transit/**`.

## 6. Geocoding source (Phase 2, plan.md section C) — used 2026-08-17

- **Title:** Nominatim (OpenStreetMap's geocoding service)
- **Publisher:** OpenStreetMap Foundation
- **URL:** `https://nominatim.openstreetmap.org/search` (public instance)
- **Usage policy:** https://operations.osmfoundation.org/policies/nominatim/ — at most
  1 request/second, descriptive `User-Agent`, no parallel requests. Enforced by
  `backend/seeding/geocoding.py`'s `NominatimGeocoder`.
- **Source type:** Free, no-API-key-required, crowd-sourced (OSM) geocoding.
- **What it's for:** Filling `Stop.location` for the 105 stops `transit_data.json`
  leaves with `latitude`/`longitude: null` (see DATA_GAPS.md §7), via
  `backend/scripts/geocode_stops.py`.
- **Status: RUN on 2026-08-17.** 71 of 105 null-coordinate stops resolved successfully
  (67.6% hit rate). 34 remain `UNKNOWN` (unresolved names — mostly informal/transit-
  specific names not in OSM, e.g. "Bar Council", "College Morh", "Metro CNG"). All 71
  resolved coordinates validated against the Islamabad/Rawalpindi bounding box
  (33.5–33.85N / 73.0–73.3E). Two resolved names show Nominatim display-name
  mismatches ("6th Road" → "Korang Town Road", "Metropolitan Corporation" →
  "Street #15") — acceptable ambiguity for these stop types; coordinates are still
  plausibly correct.
- **Reliability:** Good for well-named places (markets, hospitals, landmarks, metro
  stations). Weaker for informal stop names ("College Morh", "Bar Council") that don't
  exist as OSM place names. The bounding-box safeguard prevented any wrong-city false
  positives.
- **Dataset elements depending on it:** 71 `Stop` records with
  `coordinate_source="NOMINATIM"`, `coordinate_confidence="APPROXIMATE"`. These stops
  now have locations and participate in the routing graph and simulator.
