"""
Database adapters between the static transit models (`Route`, `RouteStop`,
`Stop`) / the realtime models (`Trip`, `StopTime`) and the pure simulation
engine (`simulation.engine.TripSchedule`).

Two directions:

- `build_trip_for_route`: **write** path. Creates a new `Trip` (and its
  `StopTime`s) from a `Route`'s current `RouteStop` sequence, using
  `simulation.timing.compute_stop_time_offsets` for the "minimum
  necessary assumption" timing. This is the minimum-viable way to get a
  demo-able `Trip` without depending on any dedicated GTFS-style
  import/seeding module (out of this workstream's ownership).
- `load_trip_schedule`: **read** path. Loads an existing `Trip`'s
  `StopTime`s (joined with `Stop` for coordinates) into a pure
  `simulation.engine.TripSchedule`, ready for `compute_position_at`.
  Used by `simulation.provider`.

Coordinate extraction follows the same `ST_X`/`ST_Y` pattern as
`api/transit/router.py` and `routing/graph.py` (see either module's
docstring for why - `Stop.location` is a PostGIS geography column that
GeoAlchemy2 loads as an opaque WKB element, not something Python code can
read lat/lon off directly).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import RouteStop, Stop, StopTime, Trip
from simulation.engine import ScheduleStop, TripSchedule
from simulation.timing import (
    DEFAULT_DWELL_SECONDS,
    SIMULATED_VEHICLE_SPEED_KMH,
    StopTimingInput,
    compute_stop_time_offsets,
)


def _longitude_expr():
    return func.ST_X(cast(Stop.location, Geometry)).label("longitude")


def _latitude_expr():
    return func.ST_Y(cast(Stop.location, Geometry)).label("latitude")


async def build_trip_for_route(
    session: AsyncSession,
    route_id: uuid.UUID,
    *,
    vehicle_id: uuid.UUID | None = None,
    scheduled_start_time: datetime | None = None,
    speed_kmh: float = SIMULATED_VEHICLE_SPEED_KMH,
    dwell_seconds: float = DEFAULT_DWELL_SECONDS,
) -> Trip:
    """Create (and flush, not commit) a new `Trip` with a full set of
    `StopTime`s derived from `route_id`'s current `RouteStop` sequence.

    This is the "minimum useful scheduling system" the task calls for:
    it reads the Route's stops in order, computes arrival/departure
    offsets via `simulation.timing.compute_stop_time_offsets`, and
    persists both the `Trip` and its `StopTime`s. The caller is
    responsible for `session.commit()` (this function only flushes, so
    `trip.id` is available for the returned object and any FK use, but
    the transaction boundary stays the caller's decision - same
    convention as the rest of this project's session-taking functions).

    Raises `ValueError` if the route has no `RouteStop`s (a Trip needs at
    least one stop to be simulable - see `TripSchedule.stops`).
    """
    result = await session.execute(
        select(RouteStop, _longitude_expr(), _latitude_expr())
        .join(Stop, RouteStop.stop_id == Stop.id)
        .where(RouteStop.route_id == route_id)
        .order_by(RouteStop.sequence)
    )
    rows = result.all()
    if not rows:
        raise ValueError(
            f"Route {route_id} has no stops; cannot build a simulated trip"
        )
    if any(latitude is None or longitude is None for _, longitude, latitude in rows):
        raise ValueError(
            f"Route {route_id} has a stop without coordinates; cannot build "
            "a simulated trip until its stops are located (see "
            "docs/DATA_GAPS.md)."
        )

    timing_inputs = [
        StopTimingInput(
            stop_id=route_stop.stop_id,
            latitude=latitude,
            longitude=longitude,
            distance_along_route_m=route_stop.distance_along_route_m,
        )
        for route_stop, longitude, latitude in rows
    ]
    offsets = compute_stop_time_offsets(
        timing_inputs, speed_kmh=speed_kmh, dwell_seconds=dwell_seconds
    )

    trip = Trip(
        route_id=route_id,
        vehicle_id=vehicle_id,
        status="scheduled",
        scheduled_start_time=scheduled_start_time or datetime.now(timezone.utc),
    )
    session.add(trip)
    await session.flush()

    stop_times = [
        StopTime(
            trip_id=trip.id,
            stop_id=timing_input.stop_id,
            sequence=index + 1,
            arrival_offset_s=offset.arrival_offset_s,
            departure_offset_s=offset.departure_offset_s,
        )
        for index, (timing_input, offset) in enumerate(zip(timing_inputs, offsets))
    ]
    session.add_all(stop_times)
    await session.flush()

    return trip


async def load_trip_schedule(
    session: AsyncSession, trip_id: uuid.UUID
) -> TripSchedule | None:
    """Load `trip_id`'s `StopTime`s (with each stop's coordinates) into a
    pure `TripSchedule`, ready for `simulation.engine.compute_position_at`.

    Returns `None` if the trip doesn't exist, has no `StopTime`s (e.g.
    a `Trip` row was created directly, bypassing `build_trip_for_route`,
    and never given a schedule), or if any stop in the schedule lacks
    coordinates (Stop.location is nullable - Phase 1 imports ~105
    unlocated stops from the canonical dataset; a schedule that can't be
    positioned is useless to the engine, so callers treat this the same
    as "no position available" rather than raising.
    """
    trip = await session.get(Trip, trip_id)
    if trip is None:
        return None

    result = await session.execute(
        select(StopTime, _longitude_expr(), _latitude_expr())
        .join(Stop, StopTime.stop_id == Stop.id)
        .where(StopTime.trip_id == trip_id)
        .order_by(StopTime.sequence)
    )
    rows = result.all()
    if not rows:
        return None

    stops = tuple(
        ScheduleStop(
            stop_id=stop_time.stop_id,
            sequence=stop_time.sequence,
            latitude=latitude,
            longitude=longitude,
            arrival_offset_s=stop_time.arrival_offset_s,
            departure_offset_s=stop_time.departure_offset_s,
        )
        for stop_time, longitude, latitude in rows
    )
    if any(stop.latitude is None or stop.longitude is None for stop in stops):
        return None

    return TripSchedule(trip_id=trip.id, route_id=trip.route_id, stops=stops)
