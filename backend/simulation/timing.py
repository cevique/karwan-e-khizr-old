"""
Timing assumptions for schedule-based simulated movement.

The existing schema (`RouteStop.distance_along_route_m`, optional) does
not, by itself, provide enough information to move a vehicle through a
Route on any kind of clock - there is no `StopTime`/timetable data yet
(this module's caller, `simulation.trip_builder`, is what first creates
`StopTime` rows at all). Per the task's explicit instruction ("introduce
the minimum necessary assumption... do NOT invent a complicated
scheduling system"), this module assumes vehicles travel each inter-stop
segment at one constant average speed and dwell at each intermediate stop
for one constant duration - nothing more elaborate. Both constants are
plain, overridable function parameters, so a future caller with better
data (real average speeds per route, real dwell times) can pass them in
without any change to this module's logic; only when *per-segment*
schedule data exists does this module stop being the right layer at all
(see `db/models/stop_time.py`'s docstring for how the replacement would
plug in - a new offset source instead of this function, not a new
consumer of it).
"""

from __future__ import annotations

import decimal
import uuid
from typing import NamedTuple

from simulation.geo import Point, haversine_distance_m

# New assumption (not sourced from Karwan-e-Khizr-specific data, same
# caveat as `routing.ride_time.AVERAGE_BUS_SPEED_KMH`, which this
# deliberately does NOT import - see `simulation/geo.py`'s docstring on
# why this package keeps its own copies rather than reaching into
# `routing/`). ~20 km/h average urban bus speed including stops/dwell/
# traffic - a commonly cited rough figure, good enough for a hackathon
# demo's sense of pacing.
SIMULATED_VEHICLE_SPEED_KMH = 20.0

# Assumed dwell time at each intermediate stop (not the final stop, which
# has nowhere to depart to - see `compute_stop_time_offsets` below).
DEFAULT_DWELL_SECONDS = 20.0


class StopTimingInput(NamedTuple):
    """One stop's position + geometry, as input to `compute_stop_time_offsets`.

    Deliberately independent of any ORM model (no `RouteStop`/`Stop`
    import here) so this function stays a pure, DB-free unit that's
    trivial to test directly - `simulation.trip_builder` is the only code
    that adapts real `RouteStop`/`Stop` rows into this shape.
    """

    stop_id: uuid.UUID
    latitude: float
    longitude: float
    distance_along_route_m: decimal.Decimal | None


class StopTimeOffset(NamedTuple):
    """The computed `(arrival_offset_s, departure_offset_s)` pair for one
    stop in a trip, both as whole seconds from the trip's start."""

    arrival_offset_s: int
    departure_offset_s: int


def compute_stop_time_offsets(
    points: list[StopTimingInput],
    *,
    speed_kmh: float = SIMULATED_VEHICLE_SPEED_KMH,
    dwell_seconds: float = DEFAULT_DWELL_SECONDS,
) -> list[StopTimeOffset]:
    """Compute arrival/departure offsets (seconds since trip start) for an
    ordered sequence of stops.

    For each consecutive pair of stops, prefers the segment distance
    implied by `distance_along_route_m` (mirroring `routing.ride_time`'s
    same preference for real route-geometry length over a straight-line
    guess) when both values are present and genuinely increasing;
    otherwise falls back to straight-line (Haversine) distance between
    the two stops' coordinates. Every stop except the last also accrues
    `dwell_seconds` before the next segment's travel time starts
    counting - the final stop has no `dwell_seconds` added, since there
    is nothing to depart to.

    The result is guaranteed non-decreasing across `points` (each
    `arrival_offset_s` is $\\geq$ the previous stop's `departure_offset_s`,
    and each stop's own `departure_offset_s` $\\geq$ its `arrival_offset_s`)
    as long as `speed_kmh > 0` and `dwell_seconds >= 0` - this is exactly
    what `simulation.engine.compute_position_at` relies on to interpolate
    correctly.

    Raises `ValueError` if `points` is empty, or if `speed_kmh`/
    `dwell_seconds` aren't usable.
    """
    if not points:
        raise ValueError("points must contain at least one stop")
    if speed_kmh <= 0:
        raise ValueError("speed_kmh must be positive")
    if dwell_seconds < 0:
        raise ValueError("dwell_seconds must not be negative")

    speed_m_per_s = speed_kmh * 1000.0 / 3600.0

    offsets: list[StopTimeOffset] = []
    previous_point: StopTimingInput | None = None
    previous_departure_s = 0.0

    for index, point in enumerate(points):
        is_last = index == len(points) - 1

        if previous_point is None:
            arrival_s = 0.0
        else:
            if (
                point.distance_along_route_m is not None
                and previous_point.distance_along_route_m is not None
                and point.distance_along_route_m
                > previous_point.distance_along_route_m
            ):
                segment_distance_m = float(
                    point.distance_along_route_m
                    - previous_point.distance_along_route_m
                )
            else:
                segment_distance_m = haversine_distance_m(
                    Point(previous_point.latitude, previous_point.longitude),
                    Point(point.latitude, point.longitude),
                )
            travel_s = segment_distance_m / speed_m_per_s
            arrival_s = previous_departure_s + travel_s

        departure_s = arrival_s if is_last else arrival_s + dwell_seconds

        offsets.append(
            StopTimeOffset(
                arrival_offset_s=round(arrival_s),
                departure_offset_s=round(departure_s),
            )
        )

        previous_point = point
        previous_departure_s = departure_s

    return offsets
