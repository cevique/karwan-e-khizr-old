"""
Trip - a single run of a Route, optionally assigned to a Vehicle, that the
simulator can move along the Route's stop sequence.

This is the minimum viable "scheduling" entity for the hackathon MVP: it
does NOT model calendars, service days, or GTFS-style trip patterns -
just "this Route, this Vehicle (once assigned), starting at this instant".
`status` is the simulator's own state machine (see `simulation.service`),
not a real-world operational status feed.

Deliberately references `Route` (owned by the foundational static-transit
models, not by this workstream) via a plain foreign key - see this
project's ownership rules: adding a new table with a FK to an existing
one is fine, only modifying `db/models/route.py` itself is out of bounds.
No relationship is added on the `Route` side (that would require editing
`route.py`); `Trip.route` below is therefore one-directional, which is
fine for a `relationship()` that doesn't need `back_populates`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.route import Route
    from db.models.stop_time import StopTime
    from db.models.vehicle import Vehicle
    from db.models.vehicle_position import VehiclePosition

# The simulator's own trip lifecycle - see `simulation.service.SimulationService`:
# "scheduled" (created, not yet running) -> "active" (simulator is moving a
# vehicle along it) -> "completed" (reached the last stop) or "cancelled"
# (stopped early via simulation control). Kept as a plain constrained
# String (matching this project's existing style - e.g. `Agency.network_type`
# - rather than a native Postgres enum type, which is more awkward to
# extend later across independently-migrating workstreams).
TRIP_STATUSES = ("scheduled", "active", "completed", "cancelled")


class Trip(TimestampMixin, Base):
    """A single run of a Route by a (possibly not-yet-assigned) Vehicle."""

    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'active', 'completed', 'cancelled')",
            name="ck_trips_status",
        ),
        Index("ix_trips_route_id_status", "route_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Trips belong fully to their Route - if the Route is removed, its
    # trips (and their StopTimes, via StopTime's own cascade) go with it.
    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Nullable: a Trip can exist "unassigned" (e.g. freshly created from a
    # Route by `simulation.trip_builder`) before a Vehicle is dispatched
    # onto it via `simulation.service.SimulationService.start_trip`.
    # ON DELETE SET NULL (not CASCADE): removing a Vehicle from the fleet
    # must not delete Trip history.
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled", server_default="scheduled"
    )

    # The instant this trip's elapsed-time clock starts counting from -
    # every `StopTime.arrival_offset_s`/`departure_offset_s` on this trip
    # is relative to this timestamp (see `simulation.engine.compute_position_at`).
    # Timezone-aware, like every other timestamp in this project.
    scheduled_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    route: Mapped["Route"] = relationship()
    vehicle: Mapped["Vehicle | None"] = relationship(back_populates="trips")

    stop_times: Mapped[list["StopTime"]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        order_by="StopTime.sequence",
    )
    positions: Mapped[list["VehiclePosition"]] = relationship(back_populates="trip")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"Trip(id={self.id!r}, route_id={self.route_id!r}, "
            f"status={self.status!r})"
        )
