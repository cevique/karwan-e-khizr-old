"""
Vehicle - a physical bus/vehicle in the simulated fleet.

Deliberately minimal for the hackathon MVP: a fleet number/identifier, an
active/enabled flag (so a vehicle can be taken out of the simulated fleet
without deleting its historical `Trip`/`VehiclePosition` rows), and a
free-form notes field for anything else that doesn't need its own column
yet. Real GPS-hardware/telemetry metadata (device IDs, last-seen-online,
etc.) is deliberately out of scope - this row only needs to identify
*which* vehicle a simulated (or, later, real) position belongs to.

See db/models/trip.py and db/models/vehicle_position.py for how this
relates to the rest of the realtime/simulation model.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.trip import Trip
    from db.models.vehicle_position import VehiclePosition


class Vehicle(TimestampMixin, Base):
    """A vehicle in the simulated (later: real) fleet."""

    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Fleet/identifier number shown to operators/passengers, e.g. "BUS-014".
    # Unique so the same physical vehicle can't be curated twice by accident.
    fleet_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)

    # Whether this vehicle is currently part of the active simulated fleet.
    # A vehicle can be deactivated (e.g. "out of service") without deleting
    # its `Trip`/`VehiclePosition` history - `Trip.vehicle_id` is nullable
    # and ON DELETE SET NULL, so trip history survives even if the vehicle
    # row itself is eventually removed.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Free-form notes (e.g. "articulated", "wheelchair-accessible"). Not
    # curated/validated - same rationale as Agency.network_type.
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Not `cascade="all, delete-orphan"`: a Trip's history should outlive
    # the Vehicle that once ran it (see `Trip.vehicle_id`'s ON DELETE
    # SET NULL below) - deleting a Vehicle must not delete Trips.
    trips: Mapped[list["Trip"]] = relationship(back_populates="vehicle")

    # Position snapshots ARE owned by the vehicle - deleting a Vehicle
    # deletes its recorded position history too.
    positions: Mapped[list["VehiclePosition"]] = relationship(
        back_populates="vehicle",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Vehicle(id={self.id!r}, fleet_number={self.fleet_number!r})"
