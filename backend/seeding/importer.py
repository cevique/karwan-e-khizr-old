"""
Persist a parsed, validated `ImportDataset` (`seeding.import_schema`) to
the database.

This is the ONLY module in this package that touches a database session -
`seeding.parsers` only turns raw input into an `ImportDataset`, and
`seeding.validation` only inspects one; this module is where that data
actually becomes `Agency`/`Route`/`Stop`/`RouteStop` rows.

Entity matching (how "create/update the appropriate entities, preserve
relationships" - the task's Import requirement - is implemented for data
with no formal external ID scheme like GTFS's `stop_id`):

- Agency: matched by `name` (the existing DB `UNIQUE` constraint - see
  `db/models/agency.py`). Re-importing data for an agency you already
  imported (or that's already in the seed dataset) reuses that same row.
- Route: matched by `(agency_id, short_name)` (the existing DB
  `UNIQUE` constraint - see `db/models/route.py`).
- Stop: matched by `ref` (the canonical dataset's stable key, persisted
  on `Stop.ref`) when a ref is present, falling back to exact `name`
  matching for legacy/admin imports that carry no ref. The ref-first
  ordering matters: `docs/transit_data.json` contains distinct stops
  that share a display name (e.g. Red Line `faizabad` vs CDA feeder
  `cda_faizabad`, both "Faizabad"), which name-only matching would
  wrongly collapse into one row. Documented limitation (see
  `backend/data/README.md`): for ref-less data, renaming a stop between
  imports, or two different sources describing the same physical stop
  under slightly different names, creates a second `Stop` row rather
  than updating the first. Good enough for the CSV/JSON MVP this task
  calls for; a real GTFS-style `stop_id` (or a geographic near-match)
  would remove this limitation but is explicitly out of scope ("do not
  build a complete GTFS ecosystem unless the repository actually
  requires it").
- RouteStop: matched by `(route_id, sequence)` (the existing DB
  `UNIQUE` constraint - see `db/models/route_stop.py`).

Every import runs inside one transaction: `validate_dataset` is called
first and, on any error-level issue, `ImportValidationError` is raised
before a single row is written. Once persistence starts, any exception
(a database error, a constraint violation this module's own matching
didn't anticipate) triggers `session.rollback()` and re-raises as
`ImportPersistenceError` - so a failed import never leaves a partially
applied dataset behind.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import cast, select
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Agency, Route, RouteStop, Stop, StopTime, Trip
from seeding.import_schema import ImportDataset, ImportTripPattern
from seeding.validation import ValidationIssue, ValidationResult, validate_dataset

# Trip/StopTime IDs are derived (not random) so a re-import of the same
# pattern + start time deterministically lands on the same rows and can
# replace them in place. This keeps the "idempotent re-import" guarantee
# the plan calls for without ever fabricating data.
_IMPORT_NS = uuid.UUID("9c1f9e26-2c3d-4f0a-9e9b-1c2d3e4f5a6b")

# Pakistan Standard Time (UTC+5) - the tz for `scheduled_start_time`, the
# project's timezone-aware convention (see `db/models/trip.py`).
PKT = timezone(timedelta(hours=5))


def trip_id_for(route_id: uuid.UUID, direction: str, start: datetime) -> uuid.UUID:
    # `start` may be either the PKT-aware value used at insert time or the
    # equivalent instant read back from Postgres (asyncpg returns
    # TIMESTAMPTZ as UTC) - normalize to PKT so both produce the same ID.
    start_pkt = start.astimezone(PKT)
    return uuid.uuid5(_IMPORT_NS, f"trip:{route_id}:{direction}:{start_pkt.isoformat()}")


def stop_time_id_for(trip_id: uuid.UUID, sequence: int) -> uuid.UUID:
    return uuid.uuid5(_IMPORT_NS, f"stoptime:{trip_id}:{sequence}")


def generate_trip_starts(pattern: ImportTripPattern, service_date: date) -> list[datetime]:
    """Expand one `ImportTripPattern` into the concrete `scheduled_start_time`
    datetimes for a full service day: exactly `total_trips_per_day` trips at
    `headway_minutes` intervals starting at `first_trip_start`, i.e.
    `start_n = first_trip_start + n * headway_minutes` for n = 0..N-1 (the
    documented CDA trip counts in `docs/TRANSIT_RESEARCH.md` are
    authoritative). `last_trip_start` is NOT used to truncate the count -
    it is a documented value from the same PDF, and for FR-01 it is 15
    minutes earlier than the arithmetic 16th trip (22:15 vs 22:00); that
    discrepancy is surfaced as a `trip_count_exceeds_last_trip_start`
    validation warning rather than silently dropping a documented trip.
    """
    first_s = _time_to_seconds(pattern.first_trip_start)
    headway_s = int(pattern.headway_minutes * 60)
    starts: list[datetime] = []
    for n in range(pattern.total_trips_per_day):
        start_s = first_s + n * headway_s
        starts.append(_seconds_to_datetime(service_date, start_s))
    return starts


def _time_to_seconds(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _seconds_to_datetime(service_date: date, seconds: int) -> datetime:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return datetime.combine(service_date, time(h, m, s), tzinfo=PKT)


class ImportValidationError(Exception):
    """Raised when `validate_dataset(dataset)` finds error-level issues.
    No database writes happen before this is raised or when it is
    raised - validation always runs to completion first."""

    def __init__(self, result: ValidationResult):
        self.result = result
        messages = "; ".join(f"[{i.code}] {i.message}" for i in result.errors)
        super().__init__(f"Import dataset failed validation: {messages}")


class ImportPersistenceError(Exception):
    """Raised when persistence itself fails after validation passed (a
    database error, or a race with concurrent writes this module's
    get-or-create matching didn't anticipate). The session has already
    been rolled back by the time this is raised - no partial import is
    left committed."""


@dataclasses.dataclass
class ImportReport:
    agencies_created: int = 0
    agencies_updated: int = 0
    stops_created: int = 0
    stops_updated: int = 0
    routes_created: int = 0
    routes_updated: int = 0
    route_stops_created: int = 0
    route_stops_updated: int = 0
    trips_created: int = 0
    trips_replaced: int = 0
    stop_times_created: int = 0
    warnings: tuple[ValidationIssue, ...] = ()


async def _get_or_create_agency(
    session: AsyncSession, name: str, network_type: str | None, report: ImportReport
) -> Agency:
    existing = (
        await session.execute(select(Agency).where(Agency.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        if network_type is not None and existing.network_type != network_type:
            existing.network_type = network_type
            report.agencies_updated += 1
        return existing
    agency = Agency(name=name, network_type=network_type)
    session.add(agency)
    await session.flush()
    report.agencies_created += 1
    return agency


async def _get_or_create_stop(
    session: AsyncSession,
    ref: str | None,
    name: str,
    latitude: float | None,
    longitude: float | None,
    confidence: str | None,
    report: ImportReport,
) -> Stop:
    # Match by the stable dataset `ref` when present (the canonical
    # transit_data.json carries it, and its stops are NOT unique by name -
    # see db/models/stop.py's `ref` docstring); fall back to the legacy
    # name heuristic for imports that carry no ref.
    if ref is not None:
        existing = (
            await session.execute(select(Stop).where(Stop.ref == ref))
        ).scalar_one_or_none()
    else:
        existing = (
            await session.execute(select(Stop).where(Stop.name == name))
        ).scalar_one_or_none()
    location = None
    if latitude is not None and longitude is not None:
        location = f"SRID=4326;POINT({longitude} {latitude})"
    if existing is not None:
        # `Stop.location` round-trips through GeoAlchemy2 as an opaque
        # WKB element (see db/models/stop.py's docstring), not something
        # comparable to a plain WKT string with `!=` - so the only
        # reliable way to detect "did this stop actually move" is to ask
        # PostGIS for the coordinates currently stored and compare those,
        # the same extraction pattern `routing/graph.py` and
        # `api/transit/router.py` already use.
        from geoalchemy2 import Geometry

        current_longitude, current_latitude = (
            await session.execute(
                select(
                    sa_func.ST_X(cast(Stop.location, Geometry)),
                    sa_func.ST_Y(cast(Stop.location, Geometry)),
                ).where(Stop.id == existing.id)
            )
        ).one()
        moved = current_longitude is None and location is not None
        if location is not None and current_longitude is not None:
            moved = (
                abs(current_longitude - longitude) > 1e-9
                or abs(current_latitude - latitude) > 1e-9
            )
        if moved:
            existing.location = location
            report.stops_updated += 1
        if existing.ref is None and ref is not None:
            existing.ref = ref
        return existing
    # Provenance (plan.md section C, Phase 2): a stop created WITH a
    # location came straight from this import dataset, so it's tagged
    # "SEED_DATUM" with whatever confidence the dataset itself carries.
    # A stop created without one is left with no provenance at all -
    # `seeding.geocoding` is what fills `coordinate_source`/
    # `coordinate_confidence` in later, once it actually finds (or fails
    # to find) coordinates for it.
    stop = Stop(
        ref=ref,
        name=name,
        location=location,
        coordinate_source="SEED_DATUM" if location is not None else None,
        coordinate_confidence=confidence if location is not None else None,
    )
    session.add(stop)
    await session.flush()
    report.stops_created += 1
    return stop


async def _get_or_create_route(
    session: AsyncSession,
    agency: Agency,
    short_name: str,
    long_name: str | None,
    color: str | None,
    report: ImportReport,
) -> Route:
    existing = (
        await session.execute(
            select(Route).where(
                Route.agency_id == agency.id, Route.short_name == short_name
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        changed = False
        if long_name is not None and existing.long_name != long_name:
            existing.long_name = long_name
            changed = True
        if color is not None and existing.color != color:
            existing.color = color
            changed = True
        if changed:
            report.routes_updated += 1
        return existing
    route = Route(
        agency_id=agency.id, short_name=short_name, long_name=long_name, color=color
    )
    session.add(route)
    await session.flush()
    report.routes_created += 1
    return route


async def _get_or_create_route_stop(
    session: AsyncSession,
    route: Route,
    stop: Stop,
    sequence: int,
    distance_along_route_m: float | None,
    report: ImportReport,
) -> RouteStop:
    existing = (
        await session.execute(
            select(RouteStop).where(
                RouteStop.route_id == route.id, RouteStop.sequence == sequence
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        changed = False
        if existing.stop_id != stop.id:
            existing.stop_id = stop.id
            changed = True
        if (
            distance_along_route_m is not None
            and existing.distance_along_route_m != distance_along_route_m
        ):
            existing.distance_along_route_m = distance_along_route_m
            changed = True
        if changed:
            report.route_stops_updated += 1
        return existing
    route_stop = RouteStop(
        route_id=route.id,
        stop_id=stop.id,
        sequence=sequence,
        distance_along_route_m=distance_along_route_m,
    )
    session.add(route_stop)
    await session.flush()
    report.route_stops_created += 1
    return route_stop


async def import_dataset(
    session: AsyncSession,
    dataset: ImportDataset,
    *,
    allow_routes_without_stops: bool = False,
    service_date: date | None = None,
) -> ImportReport:
    """Validate then persist `dataset`.

    Raises `ImportValidationError` (no writes at all) if validation finds
    any error-level issue. Raises `ImportPersistenceError` (after rolling
    back everything this call wrote) if persistence itself fails. Returns
    an `ImportReport` on success - which may still carry `warnings` (e.g.
    a non-contiguous route stop sequence) even though the import
    succeeded, since warnings never block an import.

    `allow_routes_without_stops` is forwarded to `validate_dataset` - see
    its docstring. When `dataset.trip_patterns` is non-empty, `service_date`
    is required (the calendar-day the generated trips belong to); pass it
    as a fixed, deterministic date in tests/scripts so re-imports are
    idempotent.
    """
    result = validate_dataset(dataset, allow_routes_without_stops=allow_routes_without_stops)
    if not result.is_valid:
        raise ImportValidationError(result)

    if dataset.trip_patterns and service_date is None:
        raise ImportValidationError(
            ValidationResult(
                issues=(
                    ValidationIssue(
                        "error",
                        "missing_service_date",
                        "Dataset has trip_patterns but import_dataset was "
                        "called without service_date; a service date is "
                        "required to expand patterns into Trip rows.",
                        "import_dataset",
                    ),
                )
            )
        )

    report = ImportReport(warnings=result.warnings)

    try:
        agencies_by_name: dict[str, Agency] = {}
        for import_agency in dataset.agencies:
            agencies_by_name[import_agency.name] = await _get_or_create_agency(
                session, import_agency.name, import_agency.network_type, report
            )

        stops_by_ref: dict[str, Stop] = {}
        for import_stop in dataset.stops:
            stops_by_ref[import_stop.ref] = await _get_or_create_stop(
                session,
                import_stop.ref,
                import_stop.name,
                import_stop.latitude,
                import_stop.longitude,
                import_stop.confidence,
                report,
            )

        routes_by_ref: dict[str, Route] = {}
        for import_route in dataset.routes:
            agency = agencies_by_name.get(import_route.agency)
            if agency is None:
                # Referenced but not explicitly listed in `agencies` -
                # auto-create it (network_type left unset) rather than
                # treating this as a missing reference. See
                # `import_schema.py`'s module docstring: `route.agency`
                # is a name, not a ref into `dataset.agencies`, on
                # purpose.
                agency = await _get_or_create_agency(
                    session, import_route.agency, None, report
                )
                agencies_by_name[import_route.agency] = agency
            routes_by_ref[import_route.ref] = await _get_or_create_route(
                session,
                agency,
                import_route.short_name,
                import_route.long_name,
                import_route.color,
                report,
            )

        for route_ref, route_stops in dataset.routes_with_stops().items():
            route = routes_by_ref[route_ref]
            for import_route_stop in route_stops:
                stop = stops_by_ref[import_route_stop.stop_ref]
                await _get_or_create_route_stop(
                    session,
                    route,
                    stop,
                    import_route_stop.sequence,
                    import_route_stop.distance_along_route_m,
                    report,
                )

        if dataset.trip_patterns:
            assert service_date is not None  # guarded above
            await _import_trip_patterns(
                session, dataset, routes_by_ref, stops_by_ref, service_date, report
            )

        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise ImportPersistenceError(f"Import failed and was rolled back: {exc}") from exc

    return report


async def _import_trip_patterns(
    session: AsyncSession,
    dataset: ImportDataset,
    routes_by_ref: dict[str, Route],
    stops_by_ref: dict[str, Stop],
    service_date: date,
    report: ImportReport,
) -> None:
    """Expand every `ImportTripPattern` into its day's `Trip` + `StopTime`
    rows. Deterministic IDs (`trip_id_for`/`stop_time_id_for`) mean
    re-importing the same pattern on the same service date lands on the
    same rows: existing rows with those IDs are deleted first (replace
    semantics - trips are pattern-generated, not user-edited), then the
    fresh trips are inserted."""
    for pattern in dataset.trip_patterns:
        route = routes_by_ref[pattern.route_ref]
        direction = pattern.direction.lower()
        stop_times = dataset.stop_times_for(pattern.route_ref, direction)

        for start in generate_trip_starts(pattern, service_date):
            trip_id = trip_id_for(route.id, direction, start)
            existing = (
                await session.execute(select(Trip).where(Trip.id == trip_id))
            ).scalar_one_or_none()
            if existing is not None:
                await session.delete(existing)
                await session.flush()
                report.trips_replaced += 1

            trip = Trip(
                id=trip_id,
                route_id=route.id,
                status="scheduled",
                scheduled_start_time=start,
            )
            session.add(trip)
            await session.flush()
            report.trips_created += 1

            for st in stop_times:
                stop_time = StopTime(
                    id=stop_time_id_for(trip_id, st.sequence),
                    trip_id=trip_id,
                    stop_id=stops_by_ref[st.stop_ref].id,
                    sequence=st.sequence,
                    arrival_offset_s=st.arrival_offset_s,
                    departure_offset_s=st.departure_offset_s,
                )
                session.add(stop_time)
                report.stop_times_created += 1
        await session.flush()
