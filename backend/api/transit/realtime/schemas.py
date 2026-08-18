"""
API schemas for the realtime vehicle-position API.

Reuses `Coordinates` from `api/transit/schemas.py` (imported, never
modified - see this workstream's ownership rules) rather than duplicating
an equivalent lat/lng structure, the same way `api/transit/journey_schemas.py`
already does for the journey-search API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from api.transit.schemas import Coordinates

VehiclePositionStatus = Literal["not_started", "en_route", "at_stop", "completed"]


class VehiclePositionRead(BaseModel):
    """A vehicle's current (simulated) position and state.

    Phase 4 (plan.md section G) additions beyond the original bare
    position: `bearing`/`speed_kmh` (from `simulation.engine`'s
    computation - see `SimulatedPosition`'s docstring for exactly when
    each is `None`), `route_short_name`/`route_color`/
    `current_stop_name`/`next_stop_name` (looked up by
    `api/transit/realtime/router.py`, not by the simulator itself - see
    that module's docstring for why), and `scheduled_arrival_next_stop`/
    `estimated_arrival_next_stop`/`delay_seconds` (plan.md section I: for
    a simulated vehicle, the simulator IS the schedule, so the estimated
    time always equals the scheduled time and delay is always exactly
    `0.0` - these three fields are `None` together only when there's no
    next stop to report on, i.e. `next_stop_id is None`).
    """

    vehicle_id: uuid.UUID
    trip_id: uuid.UUID
    route_id: uuid.UUID
    route_short_name: str | None = None
    route_color: str | None = None
    location: Coordinates
    bearing: float | None = None
    speed_kmh: float | None = None
    status: VehiclePositionStatus
    current_stop_id: uuid.UUID | None
    current_stop_name: str | None = None
    next_stop_id: uuid.UUID | None
    next_stop_name: str | None = None
    scheduled_arrival_next_stop: datetime | None = None
    estimated_arrival_next_stop: datetime | None = None
    delay_seconds: float | None = None
    elapsed_s: float
    as_of: datetime


class ETARead(BaseModel):
    """One stop's scheduled/estimated arrival, as returned by
    `GET /transit/realtime/vehicles/{vehicle_id}/eta` (plan.md section
    G/I). `estimated_arrival` always equals `scheduled_arrival` and
    `delay_seconds` is always `0.0` for a simulated vehicle - same
    reasoning as `VehiclePositionRead`'s docstring above.
    """

    stop_id: uuid.UUID
    stop_name: str
    sequence: int
    scheduled_arrival: datetime
    estimated_arrival: datetime
    delay_seconds: float


class VehicleETAList(BaseModel):
    """The full response body of `GET /transit/realtime/vehicles/{vehicle_id}/eta`
    (plan.md section H): every stop on the vehicle's current trip it
    hasn't yet reached, in sequence order. `etas` is `[]` (not an error)
    when the trip has already completed - see
    `api/transit/realtime/eta_router.py`'s docstring for the exact
    "hasn't yet reached" rule.
    """

    vehicle_id: uuid.UUID
    trip_id: uuid.UUID
    etas: list[ETARead]
