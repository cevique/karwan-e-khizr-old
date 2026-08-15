"""
StopTime - a single Trip's scheduled visit to a Stop, in sequence.

The minimum useful scheduling primitive for the simulator: rather than a
full GTFS-style calendar, each row just says "on this Trip, this Stop is
visited at this position in the sequence, `arrival_offset_s`/
`departure_offset_s` seconds after `Trip.scheduled_start_time`". The
simulator (`simulation.engine.compute_position_at`) interpolates a
vehicle's position between consecutive `StopTime`s using nothing but
these offsets plus each Stop's coordinates - it never needs wall-clock
"now" to be anything other than "elapsed time since `scheduled_start_time`".

`arrival_offset_s`/`departure_offset_s` are populated by
`simulation.timing.compute_stop_time_offsets` at Trip-creation time (see
`simulation.trip_builder.build_trip_for_route`) from the Route's existing
`RouteStop.distance_along_route_m` (falling back to straight-line
distance) and an assumed average speed - the "minimum necessary
assumption" the task calls for when no real timetable exists. Once real
schedule data exists, only that computation needs to change - this model
and the simulator that reads it don't.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.stop import Stop
    from db.models.trip import Trip


class StopTime(TimestampMixin, Base):
    """A Trip's scheduled arrival/departure at one Stop, in sequence."""

    __tablename__ = "stop_times"
    __table_args__ = (
        UniqueConstraint(
            "trip_id", "sequence", name="uq_stop_times_trip_id_sequence"
        ),
        CheckConstraint(
            "departure_offset_s >= arrival_offset_s",
            name="ck_stop_times_departure_not_before_arrival",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    trip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stops.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 1-based (or otherwise monotonic) position of this stop within the
    # trip - same "explicit ordering field" rationale as
    # `RouteStop.sequence`, not relying on row insertion order.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    # Seconds after `Trip.scheduled_start_time` this stop is reached /
    # left. Equal for a stop with no modeled dwell time. Always
    # non-negative and non-decreasing across a trip's ordered StopTimes
    # (enforced by `simulation.timing.compute_stop_time_offsets`, which is
    # the only code path that should ever populate these - not by a
    # database constraint spanning multiple rows, which Postgres can't
    # express as a simple CHECK).
    arrival_offset_s: Mapped[int] = mapped_column(Integer, nullable=False)
    departure_offset_s: Mapped[int] = mapped_column(Integer, nullable=False)

    trip: Mapped["Trip"] = relationship(back_populates="stop_times")
    # One-directional, like `Trip.route` - `db/models/stop.py` isn't
    # modified to add a back-reference here.
    stop: Mapped["Stop"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"StopTime(trip_id={self.trip_id!r}, stop_id={self.stop_id!r}, "
            f"sequence={self.sequence!r})"
        )
