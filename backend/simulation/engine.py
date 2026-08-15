"""
Deterministic simulation core: turns a `TripSchedule` (pure data) plus an
elapsed-seconds value into exactly one `SimulatedPosition`.

Everything in this module is a plain, DB-free, FastAPI-free function over
plain dataclasses - no randomness, no wall-clock reads, no I/O. Given the
same `TripSchedule` and the same `elapsed_s`, `compute_position_at`
always returns the same result, by construction (see the task's explicit
determinism requirement). `simulation.provider` is the layer that loads a
`TripSchedule` from the database and supplies a real elapsed-seconds
value (`now - Trip.scheduled_start_time`); this module never touches
either of those concerns itself, which is what makes it trivially unit
-testable and safely reusable if the "now" source ever changes (e.g. a
fixed clock for a demo, not just `datetime.now`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from simulation.geo import Point, interpolate_point

# See db/models/vehicle_position.py's `VEHICLE_POSITION_STATUSES` - kept
# as a plain tuple here too (not imported from `db.models`) so this module
# has zero dependency on the ORM/database layer, per the architectural
# requirement that the simulator be usable without either FastAPI or
# SQLAlchemy where practical.
NOT_STARTED = "not_started"
EN_ROUTE = "en_route"
AT_STOP = "at_stop"
COMPLETED = "completed"


@dataclass(frozen=True)
class ScheduleStop:
    """One stop within a `TripSchedule`: its position in the sequence,
    its coordinates, and when the trip reaches/leaves it."""

    stop_id: uuid.UUID
    sequence: int
    latitude: float
    longitude: float
    arrival_offset_s: int
    departure_offset_s: int


@dataclass(frozen=True)
class TripSchedule:
    """A trip's full ordered stop sequence - the only input
    `compute_position_at` needs besides an elapsed-seconds value.

    `stops` must be non-empty and sorted by `sequence`/offset (this is
    guaranteed by `simulation.timing.compute_stop_time_offsets`, the sole
    intended producer of these offsets, and by
    `simulation.provider.load_trip_schedule`'s `ORDER BY sequence` query -
    `compute_position_at` does not re-sort or validate this itself).
    """

    trip_id: uuid.UUID
    route_id: uuid.UUID
    stops: tuple[ScheduleStop, ...]


@dataclass(frozen=True)
class SimulatedPosition:
    """The simulator's answer to "where is this vehicle, right now?"."""

    trip_id: uuid.UUID
    route_id: uuid.UUID
    latitude: float
    longitude: float
    status: str
    current_stop_id: uuid.UUID | None
    next_stop_id: uuid.UUID | None
    elapsed_s: float
    vehicle_id: uuid.UUID | None = None
    as_of: datetime | None = None


def compute_position_at(
    schedule: TripSchedule,
    elapsed_s: float,
    *,
    vehicle_id: uuid.UUID | None = None,
    as_of: datetime | None = None,
) -> SimulatedPosition:
    """Compute exactly one deterministic `SimulatedPosition` for `schedule`
    at `elapsed_s` seconds since the trip's `scheduled_start_time`.

    Four cases, in order:

    1. `elapsed_s` is at or before the first stop's arrival -> parked at
       the first stop. `status` is `"not_started"` while strictly before
       it, `"at_stop"` exactly at it (boundary belongs to "arrived").
    2. `elapsed_s` is at or after the last stop's arrival -> the trip is
       over. Position clamps to the last stop; `status` is `"completed"`;
       there is no `next_stop_id`.
    3. `elapsed_s` falls within a stop's dwell window
       (`arrival_offset_s <= elapsed_s <= departure_offset_s`) -> parked
       at that stop, `status` `"at_stop"`, `next_stop_id` is the
       following stop.
    4. Otherwise `elapsed_s` falls between one stop's departure and the
       next stop's arrival -> linearly interpolated (see
       `simulation.geo.interpolate_point`) between the two, `status`
       `"en_route"`.

    Raises `ValueError` if `schedule.stops` is empty - there is nothing
    to compute a position from.
    """
    stops = schedule.stops
    if not stops:
        raise ValueError("TripSchedule.stops must not be empty")

    first, last = stops[0], stops[-1]

    def _position(
        latitude: float,
        longitude: float,
        status: str,
        current_stop_id: uuid.UUID | None,
        next_stop_id: uuid.UUID | None,
    ) -> SimulatedPosition:
        return SimulatedPosition(
            trip_id=schedule.trip_id,
            route_id=schedule.route_id,
            latitude=latitude,
            longitude=longitude,
            status=status,
            current_stop_id=current_stop_id,
            next_stop_id=next_stop_id,
            elapsed_s=elapsed_s,
            vehicle_id=vehicle_id,
            as_of=as_of,
        )

    # Case 1: not yet reached the first stop (or exactly arriving at it).
    if elapsed_s <= first.arrival_offset_s:
        status = AT_STOP if elapsed_s == first.arrival_offset_s else NOT_STARTED
        next_stop_id = stops[1].stop_id if len(stops) > 1 else None
        return _position(
            first.latitude, first.longitude, status, first.stop_id, next_stop_id
        )

    # Case 2: past (or exactly at) the end of the trip.
    if elapsed_s >= last.arrival_offset_s:
        return _position(
            last.latitude, last.longitude, COMPLETED, last.stop_id, None
        )

    # Cases 3/4: somewhere between the first and last stop.
    for current, following in zip(stops, stops[1:]):
        if current.arrival_offset_s <= elapsed_s <= current.departure_offset_s:
            return _position(
                current.latitude,
                current.longitude,
                AT_STOP,
                current.stop_id,
                following.stop_id,
            )
        if current.departure_offset_s < elapsed_s < following.arrival_offset_s:
            span_s = following.arrival_offset_s - current.departure_offset_s
            fraction = (
                (elapsed_s - current.departure_offset_s) / span_s
                if span_s > 0
                else 1.0
            )
            point = interpolate_point(
                Point(current.latitude, current.longitude),
                Point(following.latitude, following.longitude),
                fraction,
            )
            return _position(
                point.latitude,
                point.longitude,
                EN_ROUTE,
                current.stop_id,
                following.stop_id,
            )

    # Unreachable given the Case 1/2 bounds above and
    # `compute_stop_time_offsets`'s non-decreasing-offsets guarantee -
    # kept as a defensive guard rather than silently falling through.
    raise AssertionError(
        "elapsed_s not covered by any schedule bracket - schedule offsets "
        "may not be sorted/non-decreasing"
    )
