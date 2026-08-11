"""
Ride-time estimation for transit ride edges.

README.md §13 / Assumption A5: "Ride-edge travel time, where no timetable
exists, is estimated from route geometry length and an assumed average
speed." `estimate_ride_time_seconds` is that estimator - a single, plain,
swappable function, deliberately NOT a method on any search/graph class,
so a later step implementing the actual search (Dijkstra) only ever calls
it as a strategy, never embeds this logic inline. When real `StopTime`/
`Trip` schedule data eventually exists (see the routing plan's "Future
schedules" section), only this function - and how its result is used
while traversing the graph - needs to change; the graph structure and the
search algorithm itself don't.

Unlike `WalkingProvider` (routing.providers), this isn't wrapped in a
formal interface/Protocol: the routing plan calls this a "strategy/
function," not an interface, and a plain function is all that's needed to
keep it swappable (`routing.graph.build_graph` already accepts it as an
injectable parameter for exactly that reason).

**New assumption, not yet in README.md** (flagged for confirmation):
`AVERAGE_BUS_SPEED_KMH` below is a reasonable placeholder for average
urban bus speed *including* stops/dwell/traffic (README.md only pins down
the *walking* speed, ~4.5 km/h, as Assumption-adjacent text near A5/A6) -
this number should be confirmed or overridden once real route data is
available to sanity-check it against, the same way A1/A2 in the
Assumptions Log are called out for early confirmation.
"""

from __future__ import annotations

import decimal
from typing import TYPE_CHECKING

from routing.geo import Point, haversine_distance_m

if TYPE_CHECKING:
    # Only needed for type hints; imported under TYPE_CHECKING to avoid a
    # circular import, since routing.graph imports this function as its
    # default ride_time_estimator.
    from routing.graph import GraphNode

# New assumption (see module docstring): ~20 km/h average urban bus speed
# including stops, dwell time, and mixed traffic - a commonly cited rough
# figure for urban bus service, not sourced from Karwan-e-Khizr-specific
# data (none exists yet).
AVERAGE_BUS_SPEED_KMH = 20.0


def estimate_ride_time_seconds(
    from_distance_along_route_m: decimal.Decimal | None,
    to_distance_along_route_m: decimal.Decimal | None,
    from_node: GraphNode,
    to_node: GraphNode,
    *,
    speed_kmh: float = AVERAGE_BUS_SPEED_KMH,
) -> float:
    """Estimate ride time (in seconds) for a single ride-edge segment.

    Takes the raw `RouteStop.distance_along_route_m` values (not a
    `RideEdge`) plus the two stops' `GraphNode`s, rather than a `RideEdge`
    object, so this function has no dependency on `routing.graph`'s
    dataclasses at runtime and can be called while a `RideEdge` is still
    being constructed (its `duration_s` field is populated from this
    function's result).

    Preferred path: if both distance-along-route values are present *and*
    genuinely increasing (`to > from` - guards against missing/bad data
    where they're equal, reversed, or otherwise unusable), the segment
    distance is `to - from` (README's "route geometry length").

    Fallback: straight-line (Haversine) distance between the two stops'
    coordinates - used whenever `RouteStop.distance_along_route_m` hasn't
    been populated (it's an optional field - see db/models/route_stop.py),
    which is the case for every `RouteStop` seeded in Step 1's tests.
    """
    if speed_kmh <= 0:
        raise ValueError("speed_kmh must be positive")
    speed_m_per_s = speed_kmh * 1000.0 / 3600.0

    if (
        from_distance_along_route_m is not None
        and to_distance_along_route_m is not None
        and to_distance_along_route_m > from_distance_along_route_m
    ):
        segment_distance_m = float(
            to_distance_along_route_m - from_distance_along_route_m
        )
    else:
        segment_distance_m = haversine_distance_m(
            Point(from_node.latitude, from_node.longitude),
            Point(to_node.latitude, to_node.longitude),
        )

    return segment_distance_m / speed_m_per_s
