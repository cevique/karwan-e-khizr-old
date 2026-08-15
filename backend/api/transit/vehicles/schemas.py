"""
API response schemas for the vehicle/trip roster.

Deliberately separate from `db.models` - never `model_validate`'d off an
ORM instance for anything that isn't a plain scalar column (same
rationale as `api/transit/schemas.py`), though nothing here currently
needs the special-casing that module's `Coordinates` extraction does.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

TripStatus = Literal["scheduled", "active", "completed", "cancelled"]


class VehicleRead(BaseModel):
    """Public representation of a Vehicle."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fleet_number: str
    is_active: bool
    notes: str | None


class TripRead(BaseModel):
    """Public representation of a Trip."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    route_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    status: TripStatus
    scheduled_start_time: datetime
