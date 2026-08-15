"""
Dev/demo simulation control API.

Isolated in its own router (prefix `/transit/realtime/simulation`,
distinct tag) deliberately - these endpoints let a caller mutate
simulation state (assign a vehicle to a trip, spin up a demo trip from a
route, force-write a position snapshot) with **no authentication or
authorization of any kind**, which is appropriate for a hackathon
dev/demo environment and NOT for an unconditionally-exposed production
endpoint. Per the task's explicit instruction, this router is NOT
included in any shared router-registration file by this workstream (see
`api/transit/realtime/__init__.py`'s integration note) - whoever
integrates all three workstreams decides whether/when to mount it (e.g.
only in a dev/staging deployment).

Every operation here is a thin wrapper around `simulation.service.
SimulationService` - no control logic lives in this file itself, so the
same operations remain available programmatically without HTTP (see that
module's docstring).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.transit.realtime.dependencies import get_simulation_service
from api.transit.vehicles.schemas import TripRead
from db.session import get_session
from simulation.service import (
    SimulationService,
    TripNotFoundError,
    VehicleNotFoundError,
)
from simulation.timing import DEFAULT_DWELL_SECONDS, SIMULATED_VEHICLE_SPEED_KMH
from simulation.trip_builder import build_trip_for_route

router = APIRouter(
    prefix="/transit/realtime/simulation", tags=["simulation-control-dev"]
)


class StartTripRequest(BaseModel):
    vehicle_id: uuid.UUID
    start_time: datetime | None = Field(
        None, description="Defaults to now if omitted."
    )


class DemoTripRequest(BaseModel):
    vehicle_id: uuid.UUID | None = Field(
        None, description="Optionally assign and start a vehicle immediately."
    )
    speed_kmh: float = Field(SIMULATED_VEHICLE_SPEED_KMH, gt=0)
    dwell_seconds: float = Field(DEFAULT_DWELL_SECONDS, ge=0)


class SimulationStateRead(BaseModel):
    active_trip_ids: list[uuid.UUID]


@router.post("/trips/{trip_id}/start", response_model=TripRead)
async def start_trip(
    trip_id: uuid.UUID,
    body: StartTripRequest,
    session: AsyncSession = Depends(get_session),
    service: SimulationService = Depends(get_simulation_service),
) -> TripRead:
    """Assign a vehicle to a trip and mark it active."""
    try:
        trip = await service.start_trip(
            session,
            trip_id=trip_id,
            vehicle_id=body.vehicle_id,
            start_time=body.start_time,
        )
    except (TripNotFoundError, VehicleNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    await session.commit()
    return TripRead.model_validate(trip)


@router.post("/trips/{trip_id}/stop", response_model=TripRead)
async def stop_trip(
    trip_id: uuid.UUID,
    completed: bool = False,
    session: AsyncSession = Depends(get_session),
    service: SimulationService = Depends(get_simulation_service),
) -> TripRead:
    """Stop a running trip (cancelled by default, or completed)."""
    try:
        trip = await service.stop_trip(session, trip_id=trip_id, completed=completed)
    except TripNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    await session.commit()
    return TripRead.model_validate(trip)


@router.post("/routes/{route_id}/demo-trip", response_model=TripRead)
async def create_demo_trip(
    route_id: uuid.UUID,
    body: DemoTripRequest,
    session: AsyncSession = Depends(get_session),
) -> TripRead:
    """Create a demo `Trip` (+ `StopTime`s) from a Route's current stop
    sequence - the quickest way to get something simulatable for a demo.
    If `vehicle_id` is given, the trip is also immediately started."""
    try:
        trip = await build_trip_for_route(
            session,
            route_id,
            vehicle_id=body.vehicle_id,
            speed_kmh=body.speed_kmh,
            dwell_seconds=body.dwell_seconds,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if body.vehicle_id is not None:
        trip.status = "active"
        await session.flush()

    await session.commit()
    return TripRead.model_validate(trip)


@router.post("/vehicles/{vehicle_id}/record-position", response_model=dict)
async def record_vehicle_position(
    vehicle_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    service: SimulationService = Depends(get_simulation_service),
) -> dict:
    """Force-write one `VehiclePosition` snapshot for a vehicle right now."""
    position = await service.record_position(session, vehicle_id=vehicle_id)
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle has no active, schedulable trip right now",
        )
    await session.commit()
    return {"id": str(position.id), "recorded_at": position.recorded_at.isoformat()}


@router.get("/state", response_model=SimulationStateRead)
async def get_simulation_state(
    session: AsyncSession = Depends(get_session),
    service: SimulationService = Depends(get_simulation_service),
) -> SimulationStateRead:
    """Inspect currently-active trip ids - a cheap way to sanity-check
    simulation state without needing the full position API."""
    return SimulationStateRead(active_trip_ids=await service.active_trip_ids(session))
