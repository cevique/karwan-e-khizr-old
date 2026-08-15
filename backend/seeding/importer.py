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
- Stop: matched by exact `name` - there is NO database-level uniqueness
  on `Stop.name` (see that model's docstring: intentionally not modeled
  yet), so this is an application-level heuristic, not an enforced
  guarantee. Documented limitation (see `backend/data/README.md`):
  renaming a stop between imports, or two different sources describing
  the same physical stop under slightly different names, creates a
  second `Stop` row rather than updating the first. Good enough for the
  CSV/JSON MVP this task calls for; a real GTFS-style `stop_id` (or a
  geographic near-match) would remove this limitation but is explicitly
  out of scope ("do not build a complete GTFS ecosystem unless the
  repository actually requires it").
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

from sqlalchemy import cast, select
from sqlalchemy import func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Agency, Route, RouteStop, Stop
from seeding.import_schema import ImportDataset
from seeding.validation import ValidationIssue, ValidationResult, validate_dataset


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
    name: str,
    latitude: float,
    longitude: float,
    report: ImportReport,
) -> Stop:
    existing = (
        await session.execute(select(Stop).where(Stop.name == name))
    ).scalar_one_or_none()
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
        moved = (
            current_longitude is None
            or abs(current_longitude - longitude) > 1e-9
            or abs(current_latitude - latitude) > 1e-9
        )
        if moved:
            existing.location = location
            report.stops_updated += 1
        return existing
    stop = Stop(name=name, location=location)
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


async def import_dataset(session: AsyncSession, dataset: ImportDataset) -> ImportReport:
    """Validate then persist `dataset`.

    Raises `ImportValidationError` (no writes at all) if validation finds
    any error-level issue. Raises `ImportPersistenceError` (after rolling
    back everything this call wrote) if persistence itself fails. Returns
    an `ImportReport` on success - which may still carry `warnings` (e.g.
    a non-contiguous route stop sequence) even though the import
    succeeded, since warnings never block an import.
    """
    result = validate_dataset(dataset)
    if not result.is_valid:
        raise ImportValidationError(result)

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
                import_stop.name,
                import_stop.latitude,
                import_stop.longitude,
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

        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise ImportPersistenceError(f"Import failed and was rolled back: {exc}") from exc

    return report
