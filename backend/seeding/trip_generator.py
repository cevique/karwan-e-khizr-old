"""
Generate a full service day's `Trip`/`StopTime` rows for ONE
already-imported route, from the SAME canonical timetable pattern(s)
`scripts/import_transit_data.py` already imports for every route at once
(plan.md section M, Phase 5).

Deliberately does NOT reimplement Trip/StopTime creation:
`seeding.importer.import_dataset`/`_import_trip_patterns` already do
that correctly (deterministic IDs, idempotent replace-in-place, offsets
copied verbatim - see that module's docstring). This module's only job
is finding which ONE route's slice of the canonical
`docs/transit_data.json` dataset to hand back to `import_dataset` for a
NEW `service_date`, so an admin can regenerate a single route's day
without re-touching the other 25 routes or re-running the whole import
script. No new persistence path is invented here.

**Never fabricates a pattern.** Only 4 of the 26 imported routes
(FR-01, FR-04, FR-07, FR-14) have a real, officially-published
per-trip timetable in `docs/transit_data.json` today (see that file's
`trips` array, and plan.md's Phase 1/3 handoffs) - every other route
(including Red Line, which has real stops/geometry but no researched
timetable) has none. Calling `generate_daily_trips` for a route with no
pattern raises `NoCanonicalTripPattern` rather than inventing one from a
flat speed/distance assumption. `simulation.trip_builder.
build_trip_for_route` is the SEPARATE, pre-existing code path for a
demo/simulated trip on any route (plan.md section F) - this module
intentionally does not fall back to it, keeping the real-timetable and
simulated-timing paths clearly distinguished, as the task requires.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Route
from seeding.import_schema import ImportDataset, ImportRoute
from seeding.importer import ImportReport, import_dataset
from seeding.transit_data_importer import load_transit_data

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TRANSIT_DATA_PATH = BACKEND_DIR / "docs" / "transit_data.json"


class NoCanonicalTripPattern(Exception):
    """`route` has no real, researched timetable pattern in the
    canonical dataset to generate trips from - see this module's
    docstring for exactly which routes currently do (FR-01/04/07/14
    only) and why this is never worked around by fabricating one."""


def find_import_route(
    dataset: ImportDataset, route: Route, agency_name: str
) -> ImportRoute | None:
    """Find `dataset`'s `ImportRoute` entry matching an existing DB
    `Route` row.

    Matched by `(agency name, short_name)` - the exact same identity
    `seeding.importer._get_or_create_route`/`_get_or_create_agency`
    already use to decide "is this the same route" during import, so a
    route this function finds is guaranteed to be the one that produced
    (or would produce) that DB row, not a same-named coincidence.
    `agency_name` is passed in rather than read off `route.agency`
    because `Route.agency` is a lazy relationship this module has no
    reason to force-load - the caller already has (or can cheaply fetch)
    the name.

    Returns `None` if the route doesn't appear in `dataset` at all -
    e.g. it was created through the generic `/admin/import` endpoint
    with data that never came from `transit_data.json`.
    """
    for import_route in dataset.routes:
        if import_route.agency == agency_name and import_route.short_name == route.short_name:
            return import_route
    return None


def dataset_for_route(dataset: ImportDataset, route_ref: str) -> ImportDataset:
    """Slice `dataset` down to exactly one route: its own agency, its own
    `ImportRoute` entry, only the stops its `route_stops`/`trip_stop_times`
    reference, its `route_stops`, and its `trip_patterns`/
    `trip_stop_times`.

    Why slice at all, instead of just handing the whole dataset to
    `import_dataset` every time: every other route's agencies/stops/
    routes/route_stops would still resolve as harmless no-op
    get-or-create matches against already-existing rows (nothing would
    break) - but the returned `ImportReport` would then misleadingly
    read "26 routes matched, N trips created" on every single call
    instead of reporting just the one route this endpoint is actually
    about. Scoping down keeps the report - and the transaction - about
    exactly what was asked for.
    """
    import_route = next((r for r in dataset.routes if r.ref == route_ref), None)
    if import_route is None:
        raise ValueError(f"No route with ref {route_ref!r} in dataset")

    route_stops = tuple(rs for rs in dataset.route_stops if rs.route_ref == route_ref)
    stop_refs = {rs.stop_ref for rs in route_stops}
    stops = tuple(s for s in dataset.stops if s.ref in stop_refs)
    trip_patterns = tuple(p for p in dataset.trip_patterns if p.route_ref == route_ref)
    trip_stop_times = {
        key: value for key, value in dataset.trip_stop_times.items() if key[0] == route_ref
    }
    agencies = tuple(a for a in dataset.agencies if a.name == import_route.agency)

    return ImportDataset(
        agencies=agencies,
        stops=stops,
        routes=(import_route,),
        route_stops=route_stops,
        trip_patterns=trip_patterns,
        trip_stop_times=trip_stop_times,
    )


async def generate_daily_trips(
    session: AsyncSession,
    route: Route,
    agency_name: str,
    service_date: date,
    *,
    dataset: ImportDataset | None = None,
) -> ImportReport:
    """Generate (or idempotently regenerate) `route`'s full day of real
    `Trip`/`StopTime` rows for `service_date`, from its canonical
    timetable pattern(s) in `docs/transit_data.json`.

    Calling this twice for the same `(route, service_date)` is safe and
    produces the same rows both times - `seeding.importer.
    _import_trip_patterns`'s deterministic `trip_id_for`/
    `stop_time_id_for` IDs mean the second call replaces the first
    call's rows in place (`ImportReport.trips_replaced`), never
    duplicating them.

    Raises `NoCanonicalTripPattern` if `route` has no matching entry in
    `dataset` at all, or has an entry but no `trip_patterns` for it (see
    that exception's docstring - most routes are in this second
    category). Raises whatever `seeding.importer.import_dataset` itself
    raises (`ImportValidationError`/`ImportPersistenceError`) for any
    other failure - this function adds no new failure mode of its own
    beyond "no pattern to generate from".

    `dataset` is loaded fresh from `DEFAULT_TRANSIT_DATA_PATH` when not
    given explicitly (tests pass a small synthetic one instead, so they
    don't depend on the real, large research dataset).
    """
    if dataset is None:
        dataset = load_transit_data(DEFAULT_TRANSIT_DATA_PATH)

    import_route = find_import_route(dataset, route, agency_name)
    if import_route is None or not any(
        pattern.route_ref == import_route.ref for pattern in dataset.trip_patterns
    ):
        raise NoCanonicalTripPattern(
            f"Route {route.short_name!r} (agency {agency_name!r}) has no canonical "
            "trip pattern in the dataset - real timetable data exists today only "
            "for FR-01, FR-04, FR-07, and FR-14 (see docs/transit_data.json)."
        )

    scoped_dataset = dataset_for_route(dataset, import_route.ref)
    return await import_dataset(
        session, scoped_dataset, allow_routes_without_stops=True, service_date=service_date
    )
