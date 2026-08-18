"""
Per-stop ETA endpoint for a single vehicle's current trip
(plan.md section G/H/I, Phase 4).

Kept as its own router/module rather than folded into
`api/transit/realtime/router.py`, matching the file `plan.md`'s Phase 4
file list calls for (`backend/api/transit/realtime/eta_router.py`) -
there's no behavioral reason it couldn't live in `router.py` instead;
this is deliberate parity with the task's stated file layout, not a
meaningful architectural boundary. Mounted at the same
`/transit/realtime` prefix as `router.py`'s own routes (a client sees
one continuous namespace) - just a separate `APIRouter` object, wired in
alongside the others in `api/router.py`.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.transit.realtime.dependencies import get_vehicle_location_provider
from api.transit.realtime.schemas import ETARead, VehicleETAList
from db.models import Stop, StopTime
from db.session import get_session
from simulation.engine import COMPLETED
from simulation.provider import VehicleLocationProvider

router = APIRouter(prefix="/transit/realtime", tags=["realtime"])


@router.get("/vehicles/{vehicle_id}/eta", response_model=VehicleETAList)
async def get_vehicle_eta(
    vehicle_id: uuid.UUID,
    provider: VehicleLocationProvider = Depends(get_vehicle_location_provider),
    session: AsyncSession = Depends(get_session),
) -> VehicleETAList:
    """ETAs for every stop on `vehicle_id`'s current trip that it hasn't
    yet reached.

    "Hasn't yet reached" means: every `StopTime` whose `sequence` is `>=`
    the sequence of `position.next_stop_id` (the stop the vehicle is
    currently heading toward, whether en route, dwelling at the previous
    stop, or not yet departed) - or, for the single-stop-schedule edge
    case where there is no next stop at all (`next_stop_id is None` but
    the trip also isn't `completed`), the sequence of `current_stop_id`
    itself. Once the trip is `completed`, `etas` is `[]` - nothing is
    still ahead of it - not an error.

    `404`, same condition as `GET /vehicles/{vehicle_id}`, when the
    vehicle has no active position right now.
    """
    position = await provider.get_vehicle_position(vehicle_id)
    if position is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vehicle has no active position right now",
        )

    etas: list[ETARead] = []
    if position.status != COMPLETED:
        threshold_stop_id = (
            position.next_stop_id if position.next_stop_id is not None else position.current_stop_id
        )
        if threshold_stop_id is not None:
            result = await session.execute(
                select(StopTime, Stop.name)
                .join(Stop, StopTime.stop_id == Stop.id)
                .where(StopTime.trip_id == position.trip_id)
                .order_by(StopTime.sequence)
            )
            rows = result.all()
            threshold_sequence = next(
                (stop_time.sequence for stop_time, _ in rows if stop_time.stop_id == threshold_stop_id),
                None,
            )
            if threshold_sequence is not None:
                assert position.as_of is not None
                scheduled_start_time = position.as_of - timedelta(seconds=position.elapsed_s)
                for stop_time, stop_name in rows:
                    if stop_time.sequence < threshold_sequence:
                        continue
                    scheduled_arrival = scheduled_start_time + timedelta(
                        seconds=stop_time.arrival_offset_s
                    )
                    etas.append(
                        ETARead(
                            stop_id=stop_time.stop_id,
                            stop_name=stop_name,
                            sequence=stop_time.sequence,
                            scheduled_arrival=scheduled_arrival,
                            # Identical to scheduled - see
                            # VehiclePositionRead's docstring / plan.md
                            # section I: a simulated vehicle IS the
                            # schedule, so there's no independent
                            # estimate to differ from it.
                            estimated_arrival=scheduled_arrival,
                            delay_seconds=0.0,
                        )
                    )

    return VehicleETAList(vehicle_id=vehicle_id, trip_id=position.trip_id, etas=etas)
