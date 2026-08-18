"""
`VehicleLocationProvider`: the replaceable interface for "where are the
vehicles right now?", plus `SimulatedVehicleLocationProvider`, the
hackathon-appropriate implementation backed by `simulation.engine`'s
deterministic computation over the current database's `Trip`/`StopTime`
data.

Mirrors the same replaceability pattern `routing.providers.WalkingProvider`
already establishes in this project: routing code never depends on
`StraightLineWalkingProvider` directly, only on the `WalkingProvider`
Protocol, so a real provider can be substituted later. Here, callers
(the realtime API layer) depend only on `VehicleLocationProvider` - a
future `RealGpsVehicleLocationProvider` (calling an actual government/
operator GPS feed) can replace `SimulatedVehicleLocationProvider` with no
change to any caller, exactly as this task's "Realtime Provider" section
requires.

The `VehicleLocationProvider` Protocol itself is intentionally free of
any FastAPI or SQLAlchemy type in its method signatures - only
`SimulatedVehicleLocationProvider`'s *implementation* (not its public
interface) touches `AsyncSession`, and it owns its own session lifecycle
via an injectable `session_factory` rather than requiring callers to pass
a session in per call - a future non-database provider (e.g. one that
calls an HTTP API) simply wouldn't use `session_factory` at all.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Route, Trip
from db.session import AsyncSessionLocal
from simulation.engine import SimulatedPosition, compute_position_at
from simulation.geo import Point
from simulation.trip_builder import load_trip_schedule

# Matches `db.session.AsyncSessionLocal`'s shape (an async context manager
# factory), without importing SQLAlchemy types into the Protocol below.
SessionFactory = Callable[[], "AsyncSession"]
Clock = Callable[[], datetime]


def default_clock() -> datetime:
    """The default `Clock`: real wall-clock UTC time. Public (not a
    private `_default_clock`) so other modules in this package - e.g.
    `simulation.service.SimulationService` - can share the exact same
    default rather than each defining their own equivalent lambda."""
    return datetime.now(timezone.utc)


@runtime_checkable
class VehicleLocationProvider(Protocol):
    """Interface for obtaining current vehicle positions/state.

    Every method is async (even though the simulated implementation below
    does no network I/O) so a future real-GPS provider - which likely
    *would* need to make a network call - fits the same interface without
    a breaking signature change later, same rationale as
    `routing.providers.WalkingProvider.estimate_walk`.
    """

    async def get_vehicle_position(
        self, vehicle_id: uuid.UUID
    ) -> SimulatedPosition | None:
        """The given vehicle's current position, or `None` if it has no
        active trip right now."""
        ...

    async def list_active_positions(self) -> list[SimulatedPosition]:
        """Every vehicle's current position, for every trip the provider
        currently considers active. Empty list, never an error, when
        nothing is running."""
        ...

    async def get_positions_for_route(
        self, route_id: uuid.UUID
    ) -> list[SimulatedPosition]:
        """Current positions of every vehicle actively running a trip on
        the given route."""
        ...

    async def get_positions_for_trip(
        self, trip_id: uuid.UUID
    ) -> list[SimulatedPosition]:
        """The position of the vehicle assigned to the given trip - a
        list of zero or one element (zero if the trip has no vehicle
        assigned, or no schedule), kept as a list for symmetry with the
        other list-returning methods here."""
        ...


async def fetch_trips(
    session: AsyncSession,
    *,
    route_id: uuid.UUID | None = None,
    trip_id: uuid.UUID | None = None,
    vehicle_id: uuid.UUID | None = None,
    only_active: bool = True,
) -> list[Trip]:
    """Shared trip-lookup query used by both `SimulatedVehicleLocationProvider`
    and `simulation.service.SimulationService` - factored out so the two
    don't drift into two different notions of "which trips are running".
    """
    stmt = select(Trip)
    if only_active:
        stmt = stmt.where(Trip.status == "active").where(Trip.vehicle_id.is_not(None))
    if route_id is not None:
        stmt = stmt.where(Trip.route_id == route_id)
    if trip_id is not None:
        stmt = stmt.where(Trip.id == trip_id)
    if vehicle_id is not None:
        stmt = stmt.where(Trip.vehicle_id == vehicle_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _load_route_geometry(
    session: AsyncSession, route_id: uuid.UUID
) -> list[Point] | None:
    """`Route.path` (Phase 3, plan.md section D) as an ordered list of
    `simulation.geo.Point`s, or `None` when the route has no geometry yet
    (the common case today - see `plan.md`'s Phase 3 handoff: 0 real
    routes currently have geometry, since no route's full stop sequence
    is located).

    `ST_AsGeoJSON` extraction mirrors `api/transit/router.py`'s
    `_route_geometry_json_expr()` (same reason: GeoAlchemy2 loads
    `Route.path` as an opaque WKB element, not something plain Python can
    read coordinates off directly). GeoJSON LineString coordinates are
    `[longitude, latitude]` pairs; `simulation.geo.Point` is
    `(latitude, longitude)` - the conversion happens right here, at this
    DB-facing boundary, so every other file in `simulation/` - including
    `simulation.engine`, which receives the already-converted list - can
    stay in `(lat, lon)` order throughout, matching `Point`'s own
    convention.
    """
    result = await session.execute(
        select(func.ST_AsGeoJSON(cast(Route.path, Geometry))).where(Route.id == route_id)
    )
    path_json = result.scalar_one_or_none()
    if path_json is None:
        return None
    coordinates = json.loads(path_json)["coordinates"]
    return [Point(latitude=lat, longitude=lon) for lon, lat in coordinates]


class SimulatedVehicleLocationProvider:
    """`VehicleLocationProvider` implementation backed by the deterministic
    simulation engine.

    Computes positions on the fly from each active `Trip`'s `StopTime`
    schedule and the current time (`elapsed_s = now - Trip.
    scheduled_start_time`) - it never reads `VehiclePosition` rows (that
    table is the *output* history a caller can persist via
    `simulation.service.SimulationService.record_position`, not this
    provider's input), so a live query always reflects "right now",
    exactly as a real GPS provider's query would.

    Owns its own session lifecycle via `session_factory` (defaulting to
    the application's own `db.session.AsyncSessionLocal` - no second
    engine/session factory is created) rather than requiring callers to
    manage a session, and its own `clock` (defaulting to
    `datetime.now(timezone.utc)`) so tests can substitute a fixed instant
    to get fully deterministic, reproducible results end-to-end.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory = AsyncSessionLocal,
        clock: Clock = default_clock,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def _position_for_trip(
        self, session: AsyncSession, trip: Trip, now: datetime
    ) -> SimulatedPosition | None:
        schedule = await load_trip_schedule(session, trip.id)
        if schedule is None:
            return None
        # Phase 4 (plan.md section F): pass the route's real geometry
        # through when it has any, so `compute_position_at` follows the
        # road instead of a straight line - a pure `None` (most routes
        # today) reproduces the pre-Phase-4 straight-line behavior
        # exactly, so this is additive, not a behavior change for the
        # common case.
        route_geometry = await _load_route_geometry(session, trip.route_id)
        elapsed_s = (now - trip.scheduled_start_time).total_seconds()
        return compute_position_at(
            schedule,
            elapsed_s,
            vehicle_id=trip.vehicle_id,
            as_of=now,
            route_geometry=route_geometry,
        )

    async def get_vehicle_position(
        self, vehicle_id: uuid.UUID
    ) -> SimulatedPosition | None:
        now = self._clock()
        async with self._session_factory() as session:
            trips = await fetch_trips(session, vehicle_id=vehicle_id)
            if not trips:
                return None
            # MVP assumption: a vehicle has at most one active trip at a
            # time - if more than one somehow exists, the first is used.
            return await self._position_for_trip(session, trips[0], now)

    async def list_active_positions(self) -> list[SimulatedPosition]:
        now = self._clock()
        async with self._session_factory() as session:
            trips = await fetch_trips(session)
            positions = []
            for trip in trips:
                position = await self._position_for_trip(session, trip, now)
                if position is not None:
                    positions.append(position)
            return positions

    async def get_positions_for_route(
        self, route_id: uuid.UUID
    ) -> list[SimulatedPosition]:
        now = self._clock()
        async with self._session_factory() as session:
            trips = await fetch_trips(session, route_id=route_id)
            positions = []
            for trip in trips:
                position = await self._position_for_trip(session, trip, now)
                if position is not None:
                    positions.append(position)
            return positions

    async def get_positions_for_trip(
        self, trip_id: uuid.UUID
    ) -> list[SimulatedPosition]:
        now = self._clock()
        async with self._session_factory() as session:
            # Unlike the other lookups, a single trip is fetched
            # regardless of status/vehicle assignment - "where's the
            # vehicle on trip X" is a meaningful question to ask about a
            # scheduled-but-not-yet-active or already-completed trip too,
            # not just an "active" one.
            trips = await fetch_trips(session, trip_id=trip_id, only_active=False)
            if not trips or trips[0].vehicle_id is None:
                return []
            position = await self._position_for_trip(session, trips[0], now)
            return [position] if position is not None else []
