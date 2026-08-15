"""
Public, read-only realtime vehicle-position API.

Every endpoint here goes through the `VehicleLocationProvider` interface
(`api.transit.realtime.dependencies.get_vehicle_location_provider`) -
never directly through `simulation.engine`/`db.models` - so swapping the
simulated provider for a future real-GPS provider changes only that one
dependency function, not any handler in this file. Never returns a
SQLAlchemy ORM object or a `simulation.engine.SimulatedPosition`
dataclass directly - always the `VehiclePositionRead` Pydantic schema.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from api.transit.realtime.dependencies import get_vehicle_location_provider
from api.transit.realtime.schemas import VehiclePositionRead
from api.transit.schemas import Coordinates
from simulation.engine import SimulatedPosition
from simulation.provider import VehicleLocationProvider

router = APIRouter(prefix="/transit/realtime", tags=["realtime"])


def _to_schema(position: SimulatedPosition) -> VehiclePositionRead:
    """Map the provider's pure dataclass into the API's Pydantic schema.

    `vehicle_id`/`as_of` are asserted non-`None` here: every position this
    router hands out came from a provider method that always supplies
    both (see `simulation.provider.SimulatedVehicleLocationProvider`) -
    they're optional on `SimulatedPosition` itself only because
    `simulation.engine.compute_position_at` doesn't require a caller to
    supply them for its own (non-API) unit tests.
    """
    assert position.vehicle_id is not None
    assert position.as_of is not None
    return VehiclePositionRead(
        vehicle_id=position.vehicle_id,
        trip_id=position.trip_id,
        route_id=position.route_id,
        location=Coordinates(latitude=position.latitude, longitude=position.longitude),
        status=position.status,
        current_stop_id=position.current_stop_id,
        next_stop_id=position.next_stop_id,
        elapsed_s=position.elapsed_s,
        as_of=position.as_of,
    )


@router.get("/vehicles", response_model=list[VehiclePositionRead])
async def list_active_vehicle_positions(
    provider: VehicleLocationProvider = Depends(get_vehicle_location_provider),
) -> list[VehiclePositionRead]:
    """Current simulated positions of every actively-running vehicle -
    the primary feed for a frontend map. Empty list (not an error) when
    nothing is currently running."""
    positions = await provider.list_active_positions()
    return [_to_schema(p) for p in positions]


@router.get("/vehicles/{vehicle_id}", response_model=VehiclePositionRead)
async def get_vehicle_position(
    vehicle_id: uuid.UUID,
    provider: VehicleLocationProvider = Depends(get_vehicle_location_provider),
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
    return _to_schema(position)


@router.get("/routes/{route_id}/vehicles", response_model=list[VehiclePositionRead])
async def list_vehicle_positions_for_route(
    route_id: uuid.UUID,
    provider: VehicleLocationProvider = Depends(get_vehicle_location_provider),
) -> list[VehiclePositionRead]:
    """Current simulated positions of every vehicle actively running a
    trip on the given route. Empty list when none are running (including
    when `route_id` doesn't exist)."""
    positions = await provider.get_positions_for_route(route_id)
    return [_to_schema(p) for p in positions]


@router.get("/trips/{trip_id}/vehicles", response_model=list[VehiclePositionRead])
async def list_vehicle_positions_for_trip(
    trip_id: uuid.UUID,
    provider: VehicleLocationProvider = Depends(get_vehicle_location_provider),
) -> list[VehiclePositionRead]:
    """The position of the vehicle assigned to the given trip, as a list
    of zero or one element - zero when the trip has no vehicle assigned,
    no schedule, or doesn't exist."""
    positions = await provider.get_positions_for_trip(trip_id)
    return [_to_schema(p) for p in positions]
