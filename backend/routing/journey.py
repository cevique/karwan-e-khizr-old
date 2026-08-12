"""
Journey/leg reconstruction: turning a raw Step 4 search path into a
presentable internal representation.

See this project's routing plan §6 "Journey representation". Converts
`routing.search.SearchResult` (the ordered sequence of the original
`RideEdge`/`WalkEdge`/`OriginConnection`/`DestinationConnection` objects
Step 4 actually traversed) into `WalkLeg`/`RideLeg` objects grouped into a
`Journey` - still plain Python dataclasses, not SQLAlchemy models and not
API/Pydantic schemas (that mapping is a later step's job, matching the
same ORM-vs-API-schema separation already used for the static transit
API).

Like `routing.search`, this module is plain Python: no `async`, no
SQLAlchemy, no FastAPI - `build_journey` only reads an already-computed
`SearchResult`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from itertools import pairwise

from routing.graph import RideEdge, WalkEdge
from routing.search import SearchResult
from routing.snapping import DestinationConnection, OriginConnection


@dataclass(frozen=True)
class WalkLeg:
    """A single walking segment of a Journey.

    `from_stop_id`/`to_stop_id` are `None` exactly when that end is the
    virtual origin/destination point rather than a `Stop` - never both
    `None` at once (every `WalkLeg` comes from an `OriginConnection`, a
    `DestinationConnection`, or a stop-to-stop `WalkEdge`, each of which
    always has at least one real stop). This dataclass has no access to
    the origin/destination point's actual coordinates - `SearchResult`
    doesn't carry them (see `routing.snapping`) - a future API layer that
    already has the original request's coordinates can attach them if
    needed.
    """

    from_stop_id: uuid.UUID | None
    to_stop_id: uuid.UUID | None
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class RideLeg:
    """One uninterrupted ride on a single Route, formed by merging every
    consecutive `RideEdge` in the search path that shares the same
    `route_id` (see `build_journey`). `intermediate_stop_ids` are the
    stops passed through between boarding and alighting, in travel order
    - empty when boarding and alighting are directly adjacent."""

    route_id: uuid.UUID
    agency_id: uuid.UUID
    board_stop_id: uuid.UUID
    board_sequence: int
    alight_stop_id: uuid.UUID
    alight_sequence: int
    intermediate_stop_ids: tuple[uuid.UUID, ...]
    duration_s: float


@dataclass(frozen=True)
class Journey:
    """A complete origin-to-destination journey: an ordered sequence of
    `WalkLeg`/`RideLeg` objects plus aggregate totals.

    `total_duration_s`/`total_walk_m` are computed purely by summing the
    legs themselves (per this project's routing plan §6: "computed by
    summing over the legs, not stored fields threaded through the search
    itself"), NOT reused from `SearchResult.total_duration_s` - the
    search's own total includes `routing.search.TRANSFER_PENALTY_S` for
    each transfer (that's what the search actually optimizes for), while
    this total does not. The penalty is instead reflected via
    `transfer_count`, so a future consumer can factor it in explicitly
    (e.g. "18 min + 2 transfers") rather than it being folded silently
    into one opaque duration figure. Flagged as a decision worth
    confirming - see the implementation report.

    `transfer_count` counts route *switches*, not just "number of rides":
    two consecutive `RideLeg`s sharing the same `route_id` (e.g. the
    passenger walked off and back onto the very same route) do NOT count
    as a transfer - consistent with `routing.search`'s own transfer-
    penalty rule, which likewise only penalizes boarding a genuinely
    *different* route than the one most recently ridden.
    """

    legs: tuple[WalkLeg | RideLeg, ...]
    total_duration_s: float
    total_walk_m: float
    transfer_count: int


def _walk_leg_from_origin(connection: OriginConnection) -> WalkLeg:
    return WalkLeg(
        from_stop_id=None,
        to_stop_id=connection.to_stop_id,
        distance_m=connection.distance_m,
        duration_s=connection.duration_s,
    )


def _walk_leg_from_destination(connection: DestinationConnection) -> WalkLeg:
    return WalkLeg(
        from_stop_id=connection.from_stop_id,
        to_stop_id=None,
        distance_m=connection.distance_m,
        duration_s=connection.duration_s,
    )


def _walk_leg_from_walk_edge(edge: WalkEdge) -> WalkLeg:
    return WalkLeg(
        from_stop_id=edge.from_stop_id,
        to_stop_id=edge.to_stop_id,
        distance_m=edge.distance_m,
        duration_s=edge.duration_s,
    )


def _ride_leg_from_group(group: list[RideEdge]) -> RideLeg:
    """`group` is one or more consecutive `RideEdge`s sharing the same
    `route_id`, in travel order (see `build_journey`)."""
    first, last = group[0], group[-1]
    intermediate_stop_ids = tuple(edge.to_stop_id for edge in group[:-1])
    return RideLeg(
        route_id=first.route_id,
        agency_id=first.agency_id,
        board_stop_id=first.from_stop_id,
        board_sequence=first.from_sequence,
        alight_stop_id=last.to_stop_id,
        alight_sequence=last.to_sequence,
        intermediate_stop_ids=intermediate_stop_ids,
        duration_s=sum(edge.duration_s for edge in group),
    )


def _count_transfers(legs: list[WalkLeg | RideLeg]) -> int:
    """Count route switches between consecutive `RideLeg`s, in travel
    order, ignoring any `WalkLeg`s between them. Two adjacent `RideLeg`s
    sharing the same `route_id` (walked off and back onto the same route)
    do not count - see `Journey`'s docstring."""
    ride_legs = [leg for leg in legs if isinstance(leg, RideLeg)]
    return sum(
        1
        for previous, current in pairwise(ride_legs)
        if previous.route_id != current.route_id
    )


def build_journey(search_result: SearchResult) -> Journey:
    """Reconstruct a `Journey` from a Step 4 `SearchResult`.

    `search_result.edges` is always `(OriginConnection, ...middle edges...,
    DestinationConnection)` by construction (see `routing.search`'s
    docstring) - the first and last edges are handled directly as
    `WalkLeg`s; everything in between is either a `WalkEdge` (its own
    `WalkLeg`) or a run of one-or-more consecutive same-route `RideEdge`s
    (merged into a single `RideLeg` - see `_ride_leg_from_group`). Both a
    same-stop transfer (two adjacent RideEdge groups on different routes,
    no WalkEdge between them) and a walk-mediated transfer (a WalkEdge
    between two RideEdge groups on different routes) naturally produce two
    separate, adjacent `RideLeg`s; `_count_transfers` is what determines
    whether that adjacency actually represents a route switch (see its
    docstring and `Journey`'s).
    """
    edges = search_result.edges
    origin_connection = edges[0]
    destination_connection = edges[-1]
    middle_edges = edges[1:-1]

    legs: list[WalkLeg | RideLeg] = [_walk_leg_from_origin(origin_connection)]

    current_ride_group: list[RideEdge] = []

    def _flush_ride_group() -> None:
        if current_ride_group:
            legs.append(_ride_leg_from_group(list(current_ride_group)))
            current_ride_group.clear()

    for edge in middle_edges:
        if isinstance(edge, RideEdge):
            if current_ride_group and current_ride_group[-1].route_id != edge.route_id:
                _flush_ride_group()
            current_ride_group.append(edge)
        else:
            _flush_ride_group()
            legs.append(_walk_leg_from_walk_edge(edge))
    _flush_ride_group()

    legs.append(_walk_leg_from_destination(destination_connection))

    total_duration_s = sum(leg.duration_s for leg in legs)
    total_walk_m = sum(leg.distance_m for leg in legs if isinstance(leg, WalkLeg))
    transfer_count = _count_transfers(legs)

    return Journey(
        legs=tuple(legs),
        total_duration_s=total_duration_s,
        total_walk_m=total_walk_m,
        transfer_count=transfer_count,
    )
