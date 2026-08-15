"""
Read-only roster API: `Vehicle`s and `Trip`s.

Answers "what vehicles/trips exist and what's their static state"
(fleet_number, status, which route/vehicle a trip is on) - NOT "where is
this vehicle right now", which is `api/transit/realtime/router.py`'s job.
Kept as a separate router/module (own `NOT owned by main.py`
registration - see this module's own docstring at the bottom) so an
integrator can mount one without the other if ever desired, though in
practice both are meant to be included together.

Not included in `api/router.py` by this workstream - see the top-level
integration note in `api/transit/realtime/__init__.py`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.transit.vehicles.schemas import TripRead, VehicleRead
from db.models import Trip, Vehicle
from db.session import get_session

router = APIRouter(prefix="/transit", tags=["vehicles"])

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


# --------------------------------------------------------------------------
# Vehicles
# --------------------------------------------------------------------------


@router.get("/vehicles", response_model=list[VehicleRead])
async def list_vehicles(
    active_only: bool = Query(
        False, description="If true, only return vehicles with is_active=true."
    ),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[VehicleRead]:
    """List vehicles in the fleet."""
    stmt = select(Vehicle).order_by(Vehicle.fleet_number).limit(limit).offset(offset)
    if active_only:
        stmt = stmt.where(Vehicle.is_active.is_(True))
    result = await session.execute(stmt)
    return [VehicleRead.model_validate(v) for v in result.scalars().all()]


@router.get("/vehicles/{vehicle_id}", response_model=VehicleRead)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> VehicleRead:
    """Fetch a single Vehicle."""
    vehicle = await session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found"
        )
    return VehicleRead.model_validate(vehicle)


# --------------------------------------------------------------------------
# Trips
# --------------------------------------------------------------------------


@router.get("/trips", response_model=list[TripRead])
async def list_trips(
    route_id: uuid.UUID | None = Query(
        None, description="Filter to trips on this route."
    ),
    vehicle_id: uuid.UUID | None = Query(
        None, description="Filter to trips assigned to this vehicle."
    ),
    trip_status: str | None = Query(
        None,
        alias="status",
        description="Filter by trip status (scheduled/active/completed/cancelled).",
    ),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[TripRead]:
    """List trips, optionally filtered by route, vehicle, and/or status."""
    stmt = (
        select(Trip)
        .order_by(Trip.scheduled_start_time.desc())
        .limit(limit)
        .offset(offset)
    )
    if route_id is not None:
        stmt = stmt.where(Trip.route_id == route_id)
    if vehicle_id is not None:
        stmt = stmt.where(Trip.vehicle_id == vehicle_id)
    if trip_status is not None:
        stmt = stmt.where(Trip.status == trip_status)

    result = await session.execute(stmt)
    return [TripRead.model_validate(t) for t in result.scalars().all()]


@router.get("/trips/{trip_id}", response_model=TripRead)
async def get_trip(
    trip_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> TripRead:
    """Fetch a single Trip."""
    trip = await session.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found"
        )
    return TripRead.model_validate(trip)
