"""
Shortest-path search over the routing graph - "fastest", "fewest_transfers",
and "least_walking" objectives.

See README.md §13 and this project's routing plan (§2 "Routing algorithm",
§5 "Transfers"). This module is plain Python: no `async`, no SQLAlchemy, no
FastAPI - it operates entirely on the in-memory `TransitGraph` (from
`routing.graph`) plus the per-request `OriginConnection`/
`DestinationConnection` tuples already computed by `routing.snapping`
(Step 3). Nothing here touches a database session or an HTTP layer, so it
can be called, tested, and reasoned about completely independently of
either - matching this step's explicit requirement.

**Search space**: real `Stop` ids (from `graph`) plus two per-request
virtual sentinel nodes, `ORIGIN` and `DESTINATION`, representing the
arbitrary (non-`Stop`) query points. These virtual nodes and their
connecting edges exist only for the duration of a single call - they are
never added to `graph` itself (see `_build_adjacency`'s docstring for how
"never mutate the base graph" is achieved).

**Three objectives, one Dijkstra engine**: `find_shortest_path` accepts a
pluggable `edge_cost_fn` (default `fastest_edge_cost`); `fastest_edge_cost`,
`fewest_transfers_edge_cost`, and `least_walking_edge_cost` are three
different `edge_cost_fn` implementations, not three different search
algorithms. All three return a `Cost(transfers, walk_m, duration_s)` - a
small frozen, orderable, summable dataclass - and each objective only ever
sets the one or two fields its own priority actually needs, leaving the
rest at their `0`/`0.0` default; see `Cost`'s own docstring for exactly why
that makes one shared field-order comparison correct for all three at
once, with zero per-objective branching in the search loop itself.
`fastest`/`fewest_transfers`'s behavior is unchanged from Step 6 - see
`Cost`'s docstring for the precise reasoning. Both `fastest_edge_cost` and
`fewest_transfers_edge_cost` detect "is this a transfer" via the same
single helper, `_is_transfer`, so their transfer semantics can never
silently disagree with each other; `least_walking_edge_cost` doesn't call
it at all, since it deliberately never touches `transfers`.

**Transfer penalty**: applying `TRANSFER_PENALTY_S` (now in
`routing.config`, shared across objectives) correctly requires knowing, at
the moment a ride edge is considered, which route (if any) was most
recently ridden - not just "what's the cheapest way to reach this stop so
far," since the cheapest arrival might force an avoidable transfer later
while a slightly costlier arrival wouldn't. This is why Dijkstra's state
here is `(node, last_ride_route_id)`, not just `node` - see
`find_shortest_path`'s docstring.
"""

from __future__ import annotations

import heapq
import itertools
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from routing.config import TRANSFER_PENALTY_S
from routing.graph import RideEdge, TransitGraph, WalkEdge
from routing.snapping import DestinationConnection, OriginConnection


class _Origin:
    """Sentinel virtual node for the search's arbitrary origin point (not
    a `Stop` - see this module's docstring)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<ORIGIN>"


class _Destination:
    """Sentinel virtual node for the search's arbitrary destination point
    (not a `Stop` - see this module's docstring)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<DESTINATION>"


ORIGIN = _Origin()
DESTINATION = _Destination()

# A node in the per-request search space: either a real Stop id, or one of
# the two virtual sentinels above.
SearchNode = uuid.UUID | _Origin | _Destination

# The original domain object behind a _SearchEdge - exactly what
# `SearchResult.edges` is made of, so a later step can reconstruct legs
# from the real data (route ids, stop ids, sequence positions, distances)
# rather than a lossy abstraction of it.
SearchEdgeSource = RideEdge | WalkEdge | OriginConnection | DestinationConnection


@dataclass(frozen=True)
class _SearchEdge:
    """Internal, unified view of one traversable edge for the search.

    Wraps exactly one `RideEdge`/`WalkEdge`/`OriginConnection`/
    `DestinationConnection` (`source`), normalizing only the fields
    Dijkstra itself needs (`to_node`, `duration_s`, `route_id` for
    transfer detection) - deliberately not a common base class for those
    four otherwise-unrelated dataclasses, just a search-local wrapper.
    """

    to_node: SearchNode
    duration_s: float
    route_id: uuid.UUID | None
    source: SearchEdgeSource


@dataclass(frozen=True, order=True)
class Cost:
    """A generic, summable, lexicographically-ordered search cost.

    `@dataclass(order=True)` generates `__lt__`/`__le__`/etc. comparing
    fields in DECLARATION order: `transfers`, then `walk_m`, then
    `duration_s`. All three objectives (`fastest_edge_cost`,
    `fewest_transfers_edge_cost`, `least_walking_edge_cost`) share this
    one field order and one comparison - no per-objective branching
    anywhere in `find_shortest_path` - by each only ever touching the
    field(s) *its own* priority actually needs and leaving the other
    field(s) at their default `0`/`0.0` for every edge in that search.
    Since an untouched field is identically `0` for every state being
    compared within a given search, it never influences that
    comparison, so the fixed 3-tuple order transparently reduces to
    exactly the 1- or 2-field priority each objective actually wants:

    - `fastest_edge_cost`: `transfers` and `walk_m` both always `0` ->
      comparison reduces to plain `duration_s` (this project's original
      "fastest" behavior, preserved exactly).
    - `fewest_transfers_edge_cost`: `walk_m` always `0` -> reduces to
      `(transfers, duration_s)`, preserved exactly from Step 6.
    - `least_walking_edge_cost`: `transfers` always `0` -> reduces to
      `(walk_m, duration_s)` - walking distance first, duration as the
      tiebreaker, per this step's requirement.

    This is why `walk_m` is declared *between* `transfers` and
    `duration_s`, not after both: `fewest_transfers` needs `transfers`
    ahead of `duration_s`, and `least_walking` needs `walk_m` ahead of
    `duration_s` - both hold simultaneously with this one field order,
    since each objective's unused field is always the constant `0`.
    """

    transfers: int = 0
    walk_m: float = 0.0
    duration_s: float = 0.0

    def __add__(self, other: Cost) -> Cost:
        return Cost(
            self.transfers + other.transfers,
            self.walk_m + other.walk_m,
            self.duration_s + other.duration_s,
        )


EdgeCostFn = Callable[[_SearchEdge, uuid.UUID | None], Cost]


def _is_transfer(edge: _SearchEdge, last_ride_route_id: uuid.UUID | None) -> bool:
    """True exactly when traversing `edge` means boarding a ride edge for
    a route DIFFERENT from the one most recently ridden.

    The single source of truth for "what counts as a transfer" - both
    `fastest_edge_cost` and `fewest_transfers_edge_cost` call this rather
    than each re-implementing the condition, so the two objectives can
    never silently disagree about it (this step's explicit requirement).

    - `edge.route_id is None` (a `WalkEdge`/`OriginConnection`/
      `DestinationConnection`) -> never itself a transfer; only boarding a
      *ride* edge can be one.
    - `last_ride_route_id is None` -> this is the very first boarding; not
      a transfer (there's no prior route being switched away from).
    - Otherwise: a transfer exactly when the two route ids differ. Walking
      does not reset `last_ride_route_id` (see `find_shortest_path`), so a
      walk-mediated transfer between different routes is still detected
      here, while walking back onto the SAME route is not.
    """
    return (
        edge.route_id is not None
        and last_ride_route_id is not None
        and edge.route_id != last_ride_route_id
    )


def fastest_edge_cost(edge: _SearchEdge, last_ride_route_id: uuid.UUID | None) -> Cost:
    """"fastest" objective (the default): minimize total duration, with
    `TRANSFER_PENALTY_S` folded directly into `duration_s` on a transfer.
    Always returns `transfers=0`, so `Cost`'s lexicographic comparison
    reduces to plain duration comparison - reproducing this project's
    original "fastest" behavior exactly (see this module's docstring).
    """
    duration_s = edge.duration_s
    if _is_transfer(edge, last_ride_route_id):
        duration_s += TRANSFER_PENALTY_S
    return Cost(transfers=0, duration_s=duration_s)


def fewest_transfers_edge_cost(
    edge: _SearchEdge, last_ride_route_id: uuid.UUID | None
) -> Cost:
    """"fewest_transfers" objective: minimize `transfer_count` first,
    using actual (unpenalized) travel/walking duration only as the
    tiebreaker between paths with an equal transfer count. Unlike
    `fastest_edge_cost`, `TRANSFER_PENALTY_S` itself is never added here -
    transfers are penalized by being their own, higher-priority comparison
    field instead of extra time.
    """
    transfers = 1 if _is_transfer(edge, last_ride_route_id) else 0
    return Cost(transfers=transfers, duration_s=edge.duration_s)


def least_walking_edge_cost(
    edge: _SearchEdge, last_ride_route_id: uuid.UUID | None
) -> Cost:
    """"least_walking" objective: minimize total walking distance first,
    using actual (unpenalized) travel/walking duration only as the
    tiebreaker between paths with an equal walking distance.

    `edge.source` is a `RideEdge` for a ride edge (no walking distance at
    all - contributes `0.0`) or a `WalkEdge`/`OriginConnection`/
    `DestinationConnection` for anything else (each of which carries a
    real `distance_m`). `transfers` is never incremented here - this
    objective leaves transfer semantics (and `TRANSFER_PENALTY_S`)
    completely alone, exactly as `fewest_transfers_edge_cost` leaves
    walking alone; each objective only ever touches its own dimension
    (see `Cost`'s docstring for why that's what makes one shared `Cost`
    type/comparison correct for all three).
    """
    walk_m = 0.0 if isinstance(edge.source, RideEdge) else edge.source.distance_m
    return Cost(transfers=0, walk_m=walk_m, duration_s=edge.duration_s)


@dataclass(frozen=True)
class SearchResult:
    """Raw output of a shortest-path search: the total cost and the
    ordered sequence of original edge objects traversed from origin to
    destination.

    Deliberately not `Journey`/`WalkLeg`/`RideLeg`: those describe how a
    path should be *presented*, which is a later step's concern. This
    dataclass only records *what was found* - `edges[0]` is always an
    `OriginConnection` and `edges[-1]` is always a `DestinationConnection`
    (both are absent only when they'd be the very same connection - not
    possible here, since a path needs at least one edge to exist at all).
    """

    total_duration_s: float
    edges: tuple[SearchEdgeSource, ...]


def _build_adjacency(
    graph: TransitGraph,
    origin_connections: tuple[OriginConnection, ...],
    destination_connections: tuple[DestinationConnection, ...],
) -> dict[SearchNode, list[_SearchEdge]]:
    """Build a fresh, per-request adjacency map combining `graph`'s own
    ride/walk edges with this request's synthetic origin/destination
    connections.

    `graph` is only ever read here (`graph.ride_edges_by_from`/
    `graph.walk_edges_by_from`, both already read-only `MappingProxyType`s
    per `routing.graph`'s design) - a brand new `dict` is built and
    returned, so `graph` itself is never modified, appended to, or
    replaced. This is how "never mutate the cached/base TransitGraph" is
    satisfied structurally, not just by convention.
    """
    adjacency: dict[SearchNode, list[_SearchEdge]] = {}

    def _add(from_node: SearchNode, search_edge: _SearchEdge) -> None:
        adjacency.setdefault(from_node, []).append(search_edge)

    for ride_edges in graph.ride_edges_by_from.values():
        for edge in ride_edges:
            _add(
                edge.from_stop_id,
                _SearchEdge(
                    to_node=edge.to_stop_id,
                    duration_s=edge.duration_s,
                    route_id=edge.route_id,
                    source=edge,
                ),
            )

    for walk_edges in graph.walk_edges_by_from.values():
        for edge in walk_edges:
            _add(
                edge.from_stop_id,
                _SearchEdge(
                    to_node=edge.to_stop_id,
                    duration_s=edge.duration_s,
                    route_id=None,
                    source=edge,
                ),
            )

    for connection in origin_connections:
        _add(
            ORIGIN,
            _SearchEdge(
                to_node=connection.to_stop_id,
                duration_s=connection.duration_s,
                route_id=None,
                source=connection,
            ),
        )

    for connection in destination_connections:
        _add(
            connection.from_stop_id,
            _SearchEdge(
                to_node=DESTINATION,
                duration_s=connection.duration_s,
                route_id=None,
                source=connection,
            ),
        )

    return adjacency


def _reconstruct_edges(
    came_from: dict[tuple[SearchNode, uuid.UUID | None], tuple],
    final_state: tuple[SearchNode, uuid.UUID | None],
) -> tuple[SearchEdgeSource, ...]:
    """Walk `came_from` backward from `final_state` to the start state,
    then reverse, returning the original domain edge objects in the order
    they were actually traversed (origin-to-destination)."""
    edges: list[SearchEdgeSource] = []
    state = final_state
    while state in came_from:
        previous_state, search_edge = came_from[state]
        edges.append(search_edge.source)
        state = previous_state
    edges.reverse()
    return tuple(edges)


def find_shortest_path(
    graph: TransitGraph,
    origin_connections: tuple[OriginConnection, ...],
    destination_connections: tuple[DestinationConnection, ...],
    *,
    edge_cost_fn: EdgeCostFn = fastest_edge_cost,
) -> SearchResult | None:
    """Find the lowest-cost path from the virtual `ORIGIN` node to the
    virtual `DESTINATION` node, over `graph`'s ride/walk edges plus this
    request's `origin_connections`/`destination_connections` (from
    `routing.snapping`, Step 3).

    `edge_cost_fn` selects the objective: `fastest_edge_cost` (default) or
    `fewest_transfers_edge_cost` (see this module's docstring) - or any
    other function matching `EdgeCostFn`'s signature. Both ship with this
    module rather than requiring a second search implementation.

    Returns `None` - not an exception - when no path exists (a
    disconnected graph, or empty `origin_connections`/
    `destination_connections`): "no journey exists" is a normal, valid
    search outcome here, matching `routing.snapping`'s same "empty means
    empty, not an error" convention. Turning that into an HTTP response is
    a later step's job (this function has no HTTP awareness at all).

    Dijkstra's state is `(node, last_ride_route_id)` rather than just
    `node`, because the cheapest way to *reach* a stop is not necessarily
    part of the cheapest way to reach it *without an avoidable transfer
    later* - a plain `dist[node]` Dijkstra can't express that distinction,
    so it can't correctly track transfers for either objective. `None`
    here always means "no route ridden yet" (still near the true origin);
    it persists unchanged across walk edges and only changes when a ride
    edge is actually taken (see `_is_transfer`).

    The winning `SearchResult.total_duration_s` is the winning `Cost`'s
    `duration_s` component - for `fastest_edge_cost` that already includes
    any transfer penalty (matching this project's original "fastest"
    behavior exactly); for `fewest_transfers_edge_cost` it's unpenalized
    actual travel/walking time, consistent with that objective never
    adding the penalty in the first place.
    """
    adjacency = _build_adjacency(graph, origin_connections, destination_connections)

    State = tuple[SearchNode, uuid.UUID | None]
    start: State = (ORIGIN, None)

    dist: dict[State, Cost] = {start: Cost()}
    came_from: dict[State, tuple[State, _SearchEdge]] = {}
    visited: set[State] = set()

    # `counter` breaks ties in the heap purely by insertion order, so
    # heapq never needs to compare `State` tuples themselves (which mix
    # uuid.UUID and the _Origin/_Destination sentinels - not mutually
    # orderable) when two entries have equal cost.
    counter = itertools.count()
    frontier: list[tuple[Cost, int, State]] = [(Cost(), next(counter), start)]

    while frontier:
        cost, _, state = heapq.heappop(frontier)
        if state in visited:
            continue
        visited.add(state)

        node, last_ride_route_id = state
        if node is DESTINATION:
            return SearchResult(
                total_duration_s=cost.duration_s,
                edges=_reconstruct_edges(came_from, state),
            )

        for edge in adjacency.get(node, ()):
            new_cost = cost + edge_cost_fn(edge, last_ride_route_id)
            new_last_ride_route_id = (
                edge.route_id if edge.route_id is not None else last_ride_route_id
            )
            new_state: State = (edge.to_node, new_last_ride_route_id)

            if new_state in visited:
                continue
            if new_state not in dist or new_cost < dist[new_state]:
                dist[new_state] = new_cost
                came_from[new_state] = (state, edge)
                heapq.heappush(frontier, (new_cost, next(counter), new_state))

    return None
