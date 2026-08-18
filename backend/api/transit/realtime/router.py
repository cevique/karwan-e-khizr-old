"""
Public, read-only realtime vehicle-position API.

Every endpoint here goes through the `VehicleLocationProvider` interface
(`api.transit.realtime.dependencies.get_vehicle_location_provider`) -
never directly through `simulation.engine`/`db.models` for the position
itself - so swapping the simulated provider for a future real-GPS
provider changes only that one dependency function, not any handler in
this file. Never returns a SQLAlchemy ORM object or a
`simulation.engine.SimulatedPosition` dataclass directly - always the
`VehiclePositionRead` Pydantic schema.

Phase 4 (plan.md section G) exception to "never touches `db.models`
directly": this module now ALSO takes a plain `AsyncSession` (`Depends
(get_session)`, the same dependency `api/transit/router.py` already
uses) purely to batch-resolve display metadata a bare
`SimulatedPosition` doesn't carry - stop/route names and each trip's
next-stop arrival offset (see `_enrich_positions`). This is deliberately
NOT part of the `VehicleLocationProvider` Protocol: a position's
identity (where/status/bearing/speed) is the provider's job and stays
swappable; looking up how a UUID displays is an API-presentation
concern this router already owns for other reasons, the same way
`api/transit/router.py` batch-fetches Stop coordinates for a Route's
stops rather than pushing that into some other abstraction.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.transit.realtime.dependencies import get_vehicle_location_provider
from api.transit.realtime.schemas import VehiclePositionRead
from api.transit.schemas import Coordinates
from db.models import Route, Stop, StopTime
from db.session import get_session
from simulation.engine import SimulatedPosition
from simulation.provider import VehicleLocationProvider

router = APIRouter(prefix="/transit/realtime", tags=["realtime"])


async def _enrich_positions(
    session: AsyncSession, positions: list[SimulatedPosition]
) -> list[VehiclePositionRead]:
    """Turn a list of bare `SimulatedPosition`s into `VehiclePositionRead`s,
    batch-resolving every stop name, route short_name/color, and
    next-stop scheduled-arrival offset in exactly one query each - no
    N+1, the same discipline `api/transit/router.py`'s route-detail
    endpoint already follows for its own batch stop-coordinate fetch.

    `scheduled_arrival_next_stop` is derived from `position.as_of -
    elapsed_s` (== `Trip.scheduled_start_time`, see
    `simulation.provider.SimulatedVehicleLocationProvider
    ._position_for_trip`) plus the next stop's `StopTime.arrival_offset_s`
    - no second `Trip` query is needed, since `SimulatedPosition` already
    carries everything required to reconstruct it.
    """
    if not positions:
        return []

    stop_ids = {p.current_stop_id for p in positions if p.current_stop_id is not None}
    stop_ids |= {p.next_stop_id for p in positions if p.next_stop_id is not None}
    route_ids = {p.route_id for p in positions}
    trip_ids = {p.trip_id for p in positions}
    next_stop_pairs = {
        (p.trip_id, p.next_stop_id) for p in positions if p.next_stop_id is not None
    }

    stop_names: dict[uuid.UUID, str] = {}
    if stop_ids:
        result = await session.execute(select(Stop.id, Stop.name).where(Stop.id.in_(stop_ids)))
        stop_names = dict(result.all())

    route_info: dict[uuid.UUID, tuple[str, str | None]] = {}
    if route_ids:
        result = await session.execute(
            select(Route.id, Route.short_name, Route.color).where(Route.id.in_(route_ids))
        )
        route_info = {rid: (short_name, color) for rid, short_name, color in result.all()}

    next_stop_arrival_offsets: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    if next_stop_pairs:
        result = await session.execute(
            select(StopTime.trip_id, StopTime.stop_id, StopTime.arrival_offset_s).where(
                StopTime.trip_id.in_(trip_ids)
            )
        )
        for trip_id, stop_id, arrival_offset_s in result.all():
            if (trip_id, stop_id) in next_stop_pairs:
                next_stop_arrival_offsets[(trip_id, stop_id)] = arrival_offset_s

    return [
        _to_schema(p, stop_names, route_info, next_stop_arrival_offsets) for p in positions
    ]


def _to_schema(
    position: SimulatedPosition,
    stop_names: dict[uuid.UUID, str],
    route_info: dict[uuid.UUID, tuple[str, str | None]],
    next_stop_arrival_offsets: dict[tuple[uuid.UUID, uuid.UUID], int],
) -> VehiclePositionRead:
    """Map the provider's pure dataclass plus `_enrich_positions`'s
    batch-fetched lookups into the API's Pydantic schema.

    `vehicle_id`/`as_of` are asserted non-`None` here: every position this
    router hands out came from a provider method that always supplies
    both (see `simulation.provider.SimulatedVehicleLocationProvider`) -
    they're optional on `SimulatedPosition` itself only because
    `simulation.engine.compute_position_at` doesn't require a caller to
    supply them for its own (non-API) unit tests.
    """
    assert position.vehicle_id is not None
    assert position.as_of is not None

    route_short_name, route_color = route_info.get(position.route_id, (None, None))

    scheduled_arrival_next_stop = None
    estimated_arrival_next_stop = None
    delay_seconds = None
    if position.next_stop_id is not None:
        arrival_offset_s = next_stop_arrival_offsets.get(
            (position.trip_id, position.next_stop_id)
        )
        if arrival_offset_s is not None:
            scheduled_start_time = position.as_of - timedelta(seconds=position.elapsed_s)
            scheduled_arrival_next_stop = scheduled_start_time + timedelta(
                seconds=arrival_offset_s
            )
            # Simulated vehicles ARE the schedule (plan.md section I) -
            # there is no independent "actual" position to differ from
            # it, so estimated == scheduled and delay is always exactly
            # 0 here. A future real-GPS `VehicleLocationProvider` would
            # supply a genuinely different position, and this same
            # computation would then naturally produce a nonzero delay -
            # nothing here or in the schema needs to change for that,
            # only the provider (plan.md section J).
            estimated_arrival_next_stop = scheduled_arrival_next_stop
            delay_seconds = 0.0

    return VehiclePositionRead(
        vehicle_id=position.vehicle_id,
        trip_id=position.trip_id,
        route_id=position.route_id,
        route_short_name=route_short_name,
        route_color=route_color,
        location=Coordinates(latitude=position.latitude, longitude=position.longitude),
        bearing=position.bearing,
        speed_kmh=position.speed_kmh,
        status=position.status,
        current_stop_id=position.current_stop_id,
        current_stop_name=(
            stop_names.get(position.current_stop_id)
            if position.current_stop_id is not None
            else None
        ),
        next_stop_id=position.next_stop_id,
        next_stop_name=(
            stop_names.get(position.next_stop_id) if position.next_stop_id is not None else None
        ),
        scheduled_arrival_next_stop=scheduled_arrival_next_stop,
        estimated_arrival_next_stop=estimated_arrival_next_stop,
        delay_seconds=delay_seconds,
        elapsed_s=position.elapsed_s,
        as_of=position.as_of,
    )


@router.get("/vehicles", response_model=list[VehiclePositionRead])
async def list_active_vehicle_positions(
    provider: VehicleLocationProvider = Depends(get_vehicle_location_provider),
    session: AsyncSession = Depends(get_session),
) -> list[VehiclePositionRead]:
    """Current simulated positions of every actively-running vehicle -
    the primary feed for a frontend map. Empty list (not an error) when
    nothing is currently running."""
    positions = await provider.list_active_positions()
    return await _enrich_positions(session, positions)


@router.get("/vehicles/{vehicle_id}", response_model=VehiclePositionRead)
async def get_vehicle_position(
    vehicle_id: uuid.UUID,
    provider: VehicleLocationProvider = Depends(get_vehicle_location_provider),
    session: AsyncSession = Depends(get_session),
) -> VehiclePositionRead:
    """Current simulated position of a single vehicle.

    `404` when the vehicle has no active trip right now (including when
    `vehicle_id` doesn't exist at all) - "not currently running" and
    "unknown vehicle" are deliberately not distinguished here, the same
    way a real GPS feed generally can't tell the difference either.
    """
    position = await provider.get_vehicle_position(vehicle_id)
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle has no active position right now",
        )
    enriched = await _enrich_positions(session, [position])
    return enriched[0]


@router.get("/routes/{route_id}/vehicles", response_model=list[VehiclePositionRead])
async def list_vehicle_positions_for_route(
    route_id: uuid.UUID,
    provider: VehicleLocationProvider = Depends(get_vehicle_location_provider),
    session: AsyncSession = Depends(get_session),
) -> list[VehiclePositionRead]:
    """Current simulated positions of every vehicle actively running a
    trip on the given route. Empty list when none are running (including
    when `route_id` doesn't exist)."""
    positions = await provider.get_positions_for_route(route_id)
    return await _enrich_positions(session, positions)


@router.get("/trips/{trip_id}/vehicles", response_model=list[VehiclePositionRead])
async def list_vehicle_positions_for_trip(
    trip_id: uuid.UUID,
    provider: VehicleLocationProvider = Depends(get_vehicle_location_provider),
    session: AsyncSession = Depends(get_session),
) -> list[VehiclePositionRead]:
    """The position of the vehicle assigned to the given trip, as a list
    of zero or one element - zero when the trip has no vehicle assigned,
    no schedule, or doesn't exist."""
    positions = await provider.get_positions_for_trip(trip_id)
    return await _enrich_positions(session, positions)
