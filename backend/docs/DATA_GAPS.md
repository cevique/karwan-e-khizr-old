# DATA_GAPS.md

Everything OpenCode must **not** assume, plus every known gap, conflict, and
uncertainty in `transit_data.json`. Nothing in this file is resolved by picking a side
— where a conflict exists, both readings are recorded and neither is silently
preferred in the dataset.

> **UPDATE (this revision):** the original research pass concluded no stop-level
> timetable exists for this network. That conclusion was **wrong** for the CDA feeder
> network specifically, and is corrected throughout this file — see the new §0 below.
> Everything else in this file is unchanged from the original pass.

## 0. CORRECTION — CDA feeder routes DO have official stop-level timetables

CDA publishes a per-route, per-direction stop-level timetable PDF for (at least) the
`FR-*`/`FRB-*`/`FRG-*`/`ST-*` feeder network, indexed at
`https://www.cda.gov.pk/cdaTransitMap` and hosted individually at
`https://www.cda.gov.pk/Assets/metro_transit_route/<CODE>_<Forward|Backward>.pdf`. Each
PDF lists, for every trip of the day: a `Trip ID`, a `Start Time`, and a full ordered
`stop_name` / `arrival_time` / `departure_time` table — i.e. exactly the "07:10 → Stop
A, 07:17 → Stop B" shape the research brief describes as the target for realistic
simulation, not just a headway.

This research pass **directly fetched and verified** four of these PDFs in full:
**FR-01** (Backward: Khanna Pul↔NUST Metro Station, 26 stops, 16 trips/day, 60-min
headway), **FR-04** (Forward: PIMS Hospital→Bari Imam, 25 stops, 97 trips/day, 10-min
headway), **FR-07** (Forward: PIMS Hospital→Police Foundation Metro Station, 23 stops,
97 trips/day, 10-min headway), and **FR-14** (Forward: Bara Kahu→Mandi Morh, 18 stops
confirmed, 65 trips/day, 15-min headway — the departure time for one intermediate stop,
"CDA Stop," was truncated in the fetched extract and is recorded as `null` rather than
guessed). For each, multiple consecutive trips were inspected and confirmed to be exact
time-shifts of one canonical stop-time pattern by the printed headway — meaning the full
day's real trip set can be reconstructed from one canonical pattern + headway + trip
count, without inventing anything. These four are recorded in `transit_data.json`'s
`trips` array (`kind: "CANONICAL_PATTERN"`, `confidence: OFFICIAL`) with every stop
name, arrival/departure offset, and source PDF preserved.

**This does not extend to every route.** A full CDA index-page table
(`cdaTransitMap`) confirms **22 route/direction pairs exist** (FR-01, FR-03A, FR-04,
FR-04A, FR-04B, FR-05, FR-06, FR-07, FR-08A, FR-08C, FR-09, FR-10, FR-11, FR-12, FR-13,
FR-14, FR-14A, FR-15, FRB-01, FRG-1, ST-01, ST-02), each with a real official name,
headway, and its own Forward/Backward PDF pair — but **only 4 of these 22 routes' PDFs
were fetched in full in this pass** (FR-01, FR-04, FR-07, FR-14). The other 18 are
recorded in `transit_data.json`'s `routes` array with OFFICIAL name/headway/endpoint
data (from the index page) but **no ordered stop sequence or timing** — fetching and
extracting each remaining PDF is a concrete, mechanical next step (not a research
gap — the data exists and is public), flagged as **TODO, not UNKNOWN**, in each
route's `notes` field.

For three additional routes — FR-03A, FR-06, FR-09, FRG-1 — this pass captured
**partial** stop-name fragments (via search-result snippets, not a full direct fetch)
that were **not** integrated into `transit_data.json`'s `route_stops`/`trips` because
they were incomplete and their exact ordering/offsets couldn't be fully verified
end-to-end. These partial fragments are noted here for OpenCode's awareness but should
be re-fetched in full (via `web_fetch` on the specific PDF URL) rather than reused
as-is:
- **FR-03A** (PIMS Hospital↔Saidpur Village, 20-min headway): partial stops seen —
  PIMS Hospital, PIMS Metro Station, Katchery, F-8 Markaz, F-9 Park, Shaheen Chowk,
  Bahria University, Naval Complex, Faisal Masjid, Parveen Shakir Road, Kohsar Road,
  F-7 Markaz, Flower Market (endpoint "Saidpur Village" not yet confirmed reached in
  the extracted fragment).
- **FR-06** (PIMS Hospital↔Golra Sharif, 60-min headway): partial stops seen — Pims
  Metro Station, Tipu Market G-8, Ibn-e-Sina Metro Station, Chaman Metro Station,
  Taqwa Market, G-9/4 Park, Karachi Company, G-9/1 and G-9/4, G-9 Markaz, G-9/3, F-9
  Park, Shaheen Chowk, Fazaia Housing Scheme, PAF Hospital, Pakistan Gate, Maroof
  International Hospital, F-10 Markaz, IMCB F10/4, IMCG F-10/2, F-10/F-11 Chowk, Major
  Road (endpoint "Golra Sharif" not yet confirmed reached).
- **FR-09** (Khanna Pul↔Golra Morh Metro Station, 15-min headway): partial stops seen
  (mid-route onward) — Faizabad Metro Station, IJP Metro Station, Pindora Chungi,
  Katarian Chungi, Katarian Pull, CDA Stop, Pully Stop, Mandi Morh, Fauji Colony,
  Carriage Factory, Westridge, CTTI, Social Security Hospital, British Homes, Pir
  Wadhai Morh, Kohinoor Mill Colony, Kohinoor Mill, Chishtiabad, Golra Morh, Home of
  Military Transport, Golra Morh Metro Station (the route's start, near Khanna Pul,
  was not captured in the extracted fragment).
- **FRG-1** (PIMS↔Barakahu, 5-min headway): partial stops seen (Backward direction) —
  Barakahu, Shahdara, Malpur, Lake View Park, Foreign Affairs Office, Abpara, CDA,
  TNT, Children Hospital, PIMS Metro Station, Tipu Market G-8, PIMS.

**Important scope note carried forward from the original brief**: even where a full
official stop-level timetable now exists (FR-01/04/07/14), **the CDA PDFs give stop
names and times only — no stop coordinates (latitude/longitude) and no route
geometry/polyline are present in any of these PDFs.** This does not change §6/§7 below;
it only changes §5. See the new note at the end of §7.

**Secondary corroboration**: a March 2025 Daily Times article ("CDA launches 13 feeder
electric bus routes...") reporting on a CDA announcement lists each operational feeder
route with its "via" corridor description (e.g. FR-04 "via G-6, G-7 & Abpara"). These
via-descriptions are recorded as supplementary metadata in `transit_data.json`'s route
`notes` fields, not as a verified stop sequence — a via-corridor description is not the
same as an ordered, timed stop list, though for FR-01/04/07/14 the two are now
consistent with each other. This source also introduces two **new, unresolved minor
conflicts** with the CDA index page: it describes FR-11's endpoint as "I-14" where the
index page says "I-16", and describes FR-15 as "Khanna Pul-Rawat" where the index page
says "Khanna Pul-T-Chowk". Neither is resolved — both readings are preserved in
`transit_data.json`'s route `notes` field for the affected routes.

---

## 1. Missing data (confirmed absent, not just unresearched)

1. **CORRECTED — see §0 above.** Stop-level scheduled timetables DO exist and are
   officially published for the CDA feeder network, at
   `https://www.cda.gov.pk/Assets/metro_transit_route/<CODE>_<Forward|Backward>.pdf`.
   Four routes' full timetables (FR-01, FR-04, FR-07, FR-14) were fetched and imported
   into `transit_data.json`; 18 more routes are confirmed to exist with their own such
   PDFs not yet fetched (TODO, not a real-world gap). **This does NOT extend to the
   four main Metrobus lines** (Red, Orange, Blue, Green) — no stop-level timetable was
   found for those in either research pass; only headway/frequency exists for them, as
   originally reported. **Do not fabricate stop times for Red/Orange/Blue/Green or for
   the 18 not-yet-fetched feeder routes.** See TRANSIT_RESEARCH.md §8 and
   SIMULATION_DATA_SPEC.md for how to proceed for those.
2. **No public GTFS or GTFS-Realtime feed exists** for this system (confirmed by
   targeted search against GitHub/MobilityData's `awesome-transit` list/OpenMobilityData
   and general web search — nothing found).
3. **No official route geometry/polyline/shapefile/GeoJSON was found** for any of the
   four Metrobus lines or any feeder route. `Route.path` should stay `NULL` until
   geometry is reconstructed (see MAP_AND_REALTIME_RECOMMENDATIONS.md §A) or an
   official source is later found.
4. **No confirmed public developer API** for real-time vehicle positions exists today,
   despite a July-2026 CDA announcement describing an in-app (not documented external
   API) Google Maps-based live-tracking feature. Do not design against an assumed
   endpoint shape.
5. **Ordered stop sequences for Orange, Blue, Green, and all feeder routes except the
   three (FR-4, FR-7, FR-8) with a confirmed *count*** were not established in this
   research pass — only partial, unordered station-name fragments (for Orange/Blue,
   from Wikipedia's infobox image alt-text) or nothing at all (Green, most feeders).
6. **Coordinates for the majority of individual stops** (all Red Line interior stops
   not already present in the existing repository seed dataset; effectively all
   Orange/Blue/Green/feeder stops) were not established. `transit_data.json` records
   these with `latitude`/`longitude: null` and `confidence: UNKNOWN` or
   `RECONSTRUCTED` (name/position known, coordinate not).
7. **No confirmed operator-of-record split between "CDA" and "CMTA"** for day-to-day
   operations — Wikipedia's article describes CMTA as created specifically to run the
   non-Red-Line network, but nearly every practical/press source just says "CDA."
   `transit_data.json` models them as one agency (`cda_cmta`) rather than guess a
   split.
8. **No confirmed data source for informal/paratransit services** (wagons, Suzukis,
   vans widely used in both cities) — real, heavily used, but with no authoritative
   route/stop/timing source found. Deliberately excluded from `transit_data.json`
   rather than modeled with guessed data.

## 2. Unavailable APIs

- No official GTFS-RT, no confirmed REST API for CDA's real-time tracking feature
  (§1.4 above). Nothing to integrate against yet — the architecture should stay ready
  (via the existing `VehicleLocationProvider` seam), not attempt a premature
  integration.

## 3. Uncertain / conflicting routes and counts

### 3.1 Red Line station count: 24 (official) vs. 23 (only ordered list found)
Every structural/official-leaning source (Wikipedia's summary table, INCPak, Graana,
metro-status.com) states **24 stations**. The one and only *ordered, named* station
list found (rehbar.pk) lists **23 rows** while its own prose claims "24 operational
stations" — an internal inconsistency in that source. Two possibilities, neither
confirmed: (a) rehbar.pk's table is missing one real station, or (b) the "24" figure
circulating across secondary sources is itself an error that's been repeated (a common
failure mode for SEO content that cites other SEO content). **Not resolved.**
`transit_data.json` records exactly the 23 names found, in the order found, with the
route's own `official_station_count: 24` left as reported and the discrepancy noted in
the route's `notes` field.

### 3.2 Orange Line station count: 7 (Wikipedia's own table) vs. 14 (multiple listicles)
Wikipedia's structural summary table for the network states 7 stations for the Orange
Line. At least two independent secondary listicles (INCPak, icons.com.pk) state 14.
This is a larger discrepancy than could plausibly be a simple miscount, suggesting the
two figures might describe genuinely different things (e.g. "primary stations" vs.
"all stops including minor ones," or an older/newer count as the line was extended) —
but no source explains the discrepancy. **Not resolved.** No ordered stop list was
found for the Orange Line at all, so this conflict currently has no downstream effect
on `route_stops` (there are none for this route yet).

### 3.3 Blue Line: 14 names found vs. 13 official count
Wikipedia's infobox image-fragment text lists 14 apparent station names for the Blue
Line (Gulberg, Koral, Gangal, Fazaia, Lehtrar/Khanna, Zia Masjid, Kuri Road, Iqbal
Town, Dhoke Kala Khan, Sohan, I-8, H-8, G-7/G-8, PIMS Gate) against the same table's
official count of 13. Also unordered (extracted from image alt-text/captions, not a
sequential list) — so even if the count were reconciled, sequencing is still unknown.
**Not resolved; not used to build a `route_stops` sequence for this route.**

### 3.4 "Line 2" naming ambiguity (Graana.com vs. Wikipedia/others)
Graana.com's description of "Line 2" (a ~27 km corridor along Kashmir Highway parallel
to Srinagar Highway, ending at the airport) does not cleanly match Wikipedia's Orange
Line description (25.6 km, Faiz Ahmed Faiz–Airport) or its Green Line description
(15.5 km, PIMS–Bhara Kahu, Srinagar Highway). It's unclear whether Graana is describing
the Orange Line imprecisely, conflating it with the Green Line, or describing a
genuinely different/newer corridor not otherwise documented. **Not resolved** — Graana
was not used as an input to any `transit_data.json` route record for this reason.

### 3.5 CDA feeder routes — corrected and superseded by §0
**This section is superseded by §0 above and by the corrected route table in
`transit_data.json`.** The original pass relied on the graphic CDA transit-map PDF
plus Wikipedia and reconstructed route codes/descriptions that turned out to be
**inaccurate in several particulars** once the CDA's own authoritative index page
(`cdaTransitMap`) was found: there is no plain "FR-08" (it's `FR-08A` and `FR-08C`,
distinct via-Abpara and via-Faizabad variants); "FR-03A" is PIMS↔**Saidpur Village**,
not PIMS↔Faisal Masjid as the original pass guessed from the graphic PDF; there are
additional real codes the original pass never found at all (`FR-04A`, `FR-04B`
Diplomatic Enclave Shuttle, `FRB-01`, `FRG-1`). Operational status: unlike the
original pass's uncertainty, the CDA index page and a March 2025 Daily Times report
both indicate the full FR-01 through FR-15(+B/G variant) set is now operational, not
just 3–4 of them — though this pass only verified 4 routes' timetables directly (§0).
All 22 confirmed route/direction pairs are recorded in `transit_data.json` with
OFFICIAL name/headway/endpoint data; the 18 without a fetched timetable carry
`geometry: UNKNOWN` and no `route_stops`/`trips`, exactly as before, but their
existence, name, and headway are now OFFICIAL-confidence rather than the earlier,
shakier reconstruction.

## 4. Naming ambiguities affecting stop identity

### 4.1 "Faizabad" vs. "Faiz Ahmed Faiz"
Two distinct, confusingly similarly-named real Red Line stations. This research
resolves (per Wikipedia's article body text, not its image fragments) that **Faiz
Ahmed Faiz** is the Red↔Orange interchange station, and both are recorded as separate
stops. **Do not merge these into one stop under any circumstances** — a previous
version of this kind of dataset merging them by fuzzy name-matching would silently
produce a wrong interchange point.

### 4.2 "PIMS" vs. "Ibn-e-Sina"
Both names appear as apparent Red Line station labels (PIMS in the existing repo seed
dataset and in Blue/Green Line endpoint descriptions "PIMS Gate"/"PIMS Hospital"/"PIMS
- Bhara Kahu"; Ibn-e-Sina in rehbar.pk's ordered Red Line table at the position where
PIMS hospital is located geographically). It is unclear whether these are (a) the same
physical station under two different names used by different sources, (b) two
adjacent/nearby stations near the same hospital complex, or (c) an error in one
source. **Not resolved.** Recorded as two separate stop candidates in
`transit_data.json` (`ibn_e_sina` as part of the reconstructed Red Line sequence,
`pims_hospital` as a separate named-but-unsequenced stop) with an explicit note on the
`pims_hospital` record. **OpenCode must not silently merge these.**

### 4.3 "Parade Avenue Chowk" (existing seed dataset) vs. "Parade Ground" (official name)
The existing repository seed dataset's `parade_avenue` stop ("Parade Avenue Chowk") is
reused in `transit_data.json` for the officially-named "Parade Ground" station's
coordinate only, because it's the closest plausible match found — but the *names*
don't match exactly, and no independent confirmation that these are the same physical
location was found. Flagged, not silently assumed.

### 4.4 "Katchery" (official) vs. "Kachehri Chowk" (existing seed dataset)
Same situation as 4.3 — plausible same-location match (transliteration variance of the
same Urdu word), coordinate reused with that caveat, not independently confirmed.

### 4.5 Seed-dataset stops with no confirmed official counterpart
The existing repository seed dataset includes a stop named `poly_clinic` ("Poly
Clinic") on its invented "Blue Line" route between Pak Secretariat and Melody. No
source consulted in this research names "Poly Clinic" as an official Metrobus Red Line
(or any real line's) station. It may be a real place-name used informally near the
corridor, or it may be an entirely invented demo stop. **Not carried into
`transit_data.json`'s Red Line sequence** — recorded separately, unsequenced, with its
coordinate still traceable back to the seed dataset, and this uncertainty flagged
explicitly.

## 5. Missing stop-level schedules (updated)

**Corrected per §0**: `transit_data.json`'s `trips` array is no longer empty — it
holds 4 real, officially-sourced canonical trip patterns (FR-01, FR-04, FR-07, FR-14)
with real per-stop arrival/departure offsets. For every OTHER route in the dataset
(the four main Metrobus lines, and the 18 not-yet-fetched CDA feeder routes), the
original finding still holds: no stop-level scheduled time exists in any source
consulted (for Red/Orange/Blue/Green) or has not yet been fetched from an existing
official PDF (for the remaining feeder routes) — do not fabricate either. For
Red/Orange/Blue/Green specifically, if OpenCode's implementation needs `StopTime` rows
to demo the simulator, they must continue to be computed (as the existing
`simulation.timing` module already does) from an assumed speed, clearly labeled as
simulation-generated, not sourced. For the 18 not-yet-fetched feeder routes, the
correct next step is fetching their PDFs (mechanical, not a research gap), not
assumption.

## 6. Missing geometry (restated for emphasis)

No `path` field in `transit_data.json`'s `routes` array is populated. Every one is
`null` with `geometry: "UNKNOWN"`. See MAP_AND_REALTIME_RECOMMENDATIONS.md §A for the
concrete next step (OSM query / OSRM road-snapping) — this is a "not yet done," not a
"doesn't exist," gap, unlike the stop-time gap above which is a genuine absence in the
real world.

## 7. Uncertain coordinates (restated for emphasis, now including the CDA timetable PDFs)

Every coordinate in `transit_data.json` traces back to the *existing repository's* own
seed dataset, which that dataset's own documentation already describes as
"geographically plausible... NOT surveyed/GTFS-grade." This research did not upgrade
any coordinate's confidence — it only confirmed which seed-dataset stop keys plausibly
correspond to which real, confirmed station names. Treat every coordinate in the
dataset as `APPROXIMATE` at best; do not present any of them to an end user as survey-
grade or authoritative.

**This applies equally to the new, officially-sourced CDA feeder-route stops from §0.**
The CDA per-route timetable PDFs give stop **names** and **times** with OFFICIAL
confidence — but **no coordinates whatsoever**. Every one of the ~100 new stop records
added from those PDFs (`cda_*` keys) has `latitude`/`longitude: null`. Do not infer or
geocode a coordinate for any of them without saying so explicitly and marking the
result `APPROXIMATE` at best — many of these are specific, findable places (e.g. "G-10
Markaz", "NUST Metro Station", "Bar Council") that a geocoding pass or manual OSM
lookup could reasonably place, but that work was not done in this research pass and
must not be silently assumed done.

### 7.1 UPDATE (Phase 2, plan.md section C) — geocoding completed (2026-08-17)

The backend has a dedicated geocoding pipeline: `backend/seeding/geocoding.py`
(a `NominatimGeocoder` wrapping OpenStreetMap's public Nominatim `/search` endpoint,
rate-limited to 1 req/sec per Nominatim's usage policy, results validated against the
33.5–33.85N / 73.0–73.3E Islamabad/Rawalpindi bounding box before being accepted) and
`backend/scripts/geocode_stops.py` (the CLI that runs it against every `Stop` row with
`location IS NULL`). `Stop.coordinate_source` / `coordinate_confidence` (added by
migration `c3d4e5f6a7b8`) record the outcome per stop.

**Geocoding was run against the live 105 null-coordinate stops on 2026-08-17.**
Results:
- **71 stops resolved** — tagged `coordinate_source="NOMINATIM"`,
  `coordinate_confidence="APPROXIMATE"`. All within the Islamabad/Rawalpindi bounding
  box.
- **34 stops unresolved** — tagged `coordinate_confidence="UNKNOWN"`, location left
  `NULL`. These are stop names that Nominatim could not resolve to an in-bounds match
  (e.g. "Abpara Market", "Bar Council", "College Morh", "Metro CNG", "Zia Masjid").
  Most are either informal/colloquial names not in OSM, or "Metro Station" suffixed
  names where Nominatim has the underlying place but not the transit-stop-specific name.
- **17 SEED_DATUM stops** — unchanged, coordinates untouched. Their
  `coordinate_source="SEED_DATUM"` and `coordinate_confidence="APPROXIMATE"` were
  set at import time.
- **Total: 88 of 122 stops now have coordinates** (72%). 34 remain without.

After geocoding, the routing graph builds with 88 nodes (up from 17 before geocoding).
The 34 unresolved stops are skipped by the graph (they have no location) and by the
simulator (same guard).

## 8. What OpenCode must not assume

- Must not assume the existing seed dataset's route structure ("blue line" =
  Pak Secretariat–Faizabad, "red line" = Faizabad–Saddar) matches the real network's
  route structure (the real Red Line is one single Pak Secretariat–Saddar corridor).
  These are different things; keeping the demo seed dataset as-is is fine, but it
  should not be presented as "the real Metrobus network."
- Must not assume any coordinate in `transit_data.json` is survey-accurate.
- Must not assume `Route.path` should be populated with a straight-line or
  interpolated-from-stops polyline as a stand-in for real geometry — leave it `NULL`
  until real/reconstructed road-following geometry exists (a straight-line "geometry"
  is strictly worse than no geometry, since the simulator already has a straight-line
  fallback when geometry is absent).
- Must not assume the Orange Line's interchange is at "Faizabad" (it's "Faiz Ahmed
  Faiz" — see §4.1).
- Must not assume any operator "CDA route" API, feed, or fixed schema exists to
  integrate against — none was confirmed.
- Must not assume the 7-vs-14 (Orange) or 24-vs-23 (Red) station-count conflicts are
  resolved by this research — they aren't; build against whichever concrete list
  exists (the 23-name Red Line list) and treat routes without any list as legitimately
  "no ordered sequence yet," not as an invitation to invent one to match a headline
  count.
- Must not assume the CDA feeder-route timetable PDFs (§0) give coordinates or
  geometry — they give stop names and times only. Geometry/coordinates for these
  routes still need the same treatment as everything else in §6/§7.
- Must not assume all 22 CDA feeder route/direction pairs have been fully imported —
  only 4 (FR-01, FR-04, FR-07, FR-14) have real stop-level `trips` data in
  `transit_data.json`; the other 18 need their PDFs fetched (a mechanical task, listed
  per-route in each route's `notes` field) before they can be simulated realistically.
- Must not assume the Red/Orange/Blue/Green Metrobus lines now have stop-level
  timetables just because the feeder network does — they still don't (§1).
- The geocoding pipeline built in Phase 2 (§7.1) has been run. 88 of 122 stops now
  have coordinates (17 SEED_DATUM + 71 NOMINATIM). 34 stops remain `UNKNOWN` (null
  location) — mostly informal stop names not in OSM. Do not fabricate coordinates for
  them.
