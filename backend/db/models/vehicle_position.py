"""
VehiclePosition - a point-in-time snapshot of a Vehicle's (simulated, for
now) location and state.

This is deliberately an append-only history table, not a single
"latest position" row per Vehicle: `simulation.service.SimulationService.
record_position` inserts a new row each time it's called (e.g. from a
demo/dev "tick" control endpoint), and `latest position for vehicle X` is
just "the row with the greatest `recorded_at` for that `vehicle_id`" -
indexed via `ix_vehicle_positions_vehicle_id_recorded_at` below for that
exact query. The live map/API path
(`simulation.provider.SimulatedVehicleLocationProvider`) does NOT read
this table at all - it computes positions on the fly from `Trip`/
`StopTime` and the current time, which is always up to date; this table
exists for whichever consumer wants a persisted trail (history, replay,
debugging) rather than only "right now".

`latitude`/`longitude` are stored as plain floats here (not a PostGIS
`geography`/`geometry` column like `Stop.location`): this table is never
the target of a spatial proximity query (that's what `Stop`/`RouteStop`
are for), it's simulation output to be read back and serialized as-is -
a plain column avoids the WKB-extraction dance `api/transit/router.py`'s
docstring describes for exactly that reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.stop import Stop
    from db.models.trip import Trip
    from db.models.vehicle import Vehicle

# The simulator's per-position status - see `simulation.engine.compute_position_at`,
# which is the sole producer of this value. "not_started": the trip's
# scheduled_start_time hasn't been reached yet. "at_stop": within a stop's
# dwell window. "en_route": interpolating between two stops. "completed":
# past the last StopTime.
VEHICLE_POSITION_STATUSES = ("not_started", "en_route", "at_stop", "completed")


class VehiclePosition(TimestampMixin, Base):
    """A single recorded (simulated) position of a Vehicle at a moment in time."""

    __tablename__ = "vehicle_positions"
    __table_args__ = (
        Index(
            "ix_vehicle_positions_vehicle_id_recorded_at",
            "vehicle_id",
            "recorded_at",
        ),
        CheckConstraint(
            "status IN ('not_started', 'en_route', 'at_stop', 'completed')",
            name="ck_vehicle_positions_status",
        ),
        CheckConstraint(
            "latitude >= -90 AND latitude <= 90",
            name="ck_vehicle_positions_latitude_range",
        ),
        CheckConstraint(
            "longitude >= -180 AND longitude <= 180",
            name="ck_vehicle_positions_longitude_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: kept even if the originating Trip is later deleted (SET
    # NULL, not CASCADE) - a Vehicle's recorded position history is more
    # valuable kept-but-orphaned than silently deleted alongside a Trip.
    trip_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trips.id", ondelete="SET NULL"), nullable=True, index=True
    )

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    # When this simulated position was computed/recorded. Distinct from
    # `TimestampMixin.created_at` (when the row was inserted) even though
    # in practice they're set within the same instant - `recorded_at` is
    # the semantically meaningful "as of" time a consumer should use.
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Nullable: e.g. "not_started" positions have a current stop (the
    # trip's first stop) but "completed" positions have no next stop.
    current_stop_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stops.id", ondelete="SET NULL"), nullable=True
    )
    next_stop_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stops.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False)

    vehicle: Mapped["Vehicle"] = relationship(back_populates="positions")
    trip: Mapped["Trip | None"] = relationship(back_populates="positions")
    # One-directional (see StopTime.stop's docstring for why) - two FKs to
    # the same table, so each needs its own explicit `foreign_keys`.
    current_stop: Mapped["Stop | None"] = relationship(foreign_keys=[current_stop_id])
    next_stop: Mapped["Stop | None"] = relationship(foreign_keys=[next_stop_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"VehiclePosition(vehicle_id={self.vehicle_id!r}, "
            f"recorded_at={self.recorded_at!r}, status={self.status!r})"
        )
