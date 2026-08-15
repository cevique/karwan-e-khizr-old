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
    """A vehicle's current (simulated) position and state."""

    vehicle_id: uuid.UUID
    trip_id: uuid.UUID
    route_id: uuid.UUID
    location: Coordinates
    status: VehiclePositionStatus
    current_stop_id: uuid.UUID | None
    next_stop_id: uuid.UUID | None
    elapsed_s: float
    as_of: datetime
