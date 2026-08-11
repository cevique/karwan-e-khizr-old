"""
Shortest-path search over the routing graph ("fastest" objective).

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

**Transfer penalty**: applying `TRANSFER_PENALTY_S` correctly requires
knowing, at the moment a ride edge is considered, which route (if any) was
most recently ridden - not just "what's the cheapest way to reach this
stop so far," since the cheapest arrival might force an avoidable
transfer later while a slightly costlier arrival wouldn't. This is why
Dijkstra's state here is `(node, last_ride_route_id)`, not just `node` -
see `find_shortest_path`'s docstring.

**Pluggable objective (for a later step)**: the per-edge cost computation
is an injectable `edge_cost_fn` parameter (default `_fastest_edge_cost`),
not inlined into the search loop. A different scalar objective - e.g.
weighting transfers heavily enough to approximate "fewest transfers" while
staying within the same scalar-Dijkstra structure used here - can be
substituted without changing `find_shortest_path` itself. (A true
lexicographic (transfers, time) objective would need a further change to
how costs are compared, not just a different `edge_cost_fn` - that's a
decision for whichever later step actually implements it, not foreclosed
by anything here.)
"""

from __future__ import annotations

import heapq
import itertools
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from routing.graph import RideEdge, TransitGraph, WalkEdge
from routing.snapping import DestinationConnection, OriginConnection

# Fixed friction penalty applied when a path switches from one Route to a
# different Route (same-stop or walk-mediated - see `_fastest_edge_cost`).
# **New assumption, not yet in README.md** (flagged for confirmation, same
# treatment as `routing.ride_time.AVERAGE_BUS_SPEED_KMH`): 4 minutes is a
# reasonable placeholder representing wait/alighting/boarding friction at
# the new route, not sourced from Karwan-e-Khizr-specific data (none
# exists yet).
TRANSFER_PENALTY_S = 240.0


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


EdgeCostFn = Callable[[_SearchEdge, uuid.UUID | None], float]


def _fastest_edge_cost(edge: _SearchEdge, last_ride_route_id: uuid.UUID | None) -> float:
    """Default ("fastest") per-edge cost: the edge's own duration, plus
    `TRANSFER_PENALTY_S` if traversing this ride edge means switching away
    from the route most recently ridden.

    `last_ride_route_id` is `None` only before the very first ride edge is
    boarded (still walking from/near the true origin) - boarding never
    incurs a penalty in that case, since there's no prior route being
    switched away from. It is NOT reset to `None` by walk edges (walking
    doesn't erase "which route you were just on" - see
    `find_shortest_path`'s state-transition logic), so a walk-mediated
    transfer between two different routes' stops still incurs the penalty,
    same as an immediate same-stop transfer - matching this project's
    routing plan §5.
    """
    if (
        edge.route_id is not None
        and last_ride_route_id is not None
        and edge.route_id != last_ride_route_id
    ):
        return edge.duration_s + TRANSFER_PENALTY_S
    return edge.duration_s


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
    edge_cost_fn: EdgeCostFn = _fastest_edge_cost,
) -> SearchResult | None:
    """Find the lowest-cost path from the virtual `ORIGIN` node to the
    virtual `DESTINATION` node, over `graph`'s ride/walk edges plus this
    request's `origin_connections`/`destination_connections` (from
    `routing.snapping`, Step 3).

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
    so it can't correctly account for `TRANSFER_PENALTY_S`. `None` here
    always means "no route ridden yet" (still near the true origin); it
    persists unchanged across walk edges and only changes when a ride edge
    is actually taken (see `_fastest_edge_cost`).
    """
    adjacency = _build_adjacency(graph, origin_connections, destination_connections)

    State = tuple[SearchNode, uuid.UUID | None]
    start: State = (ORIGIN, None)

    dist: dict[State, float] = {start: 0.0}
    came_from: dict[State, tuple[State, _SearchEdge]] = {}
    visited: set[State] = set()

    # `counter` breaks ties in the heap purely by insertion order, so
    # heapq never needs to compare `State` tuples themselves (which mix
    # uuid.UUID and the _Origin/_Destination sentinels - not mutually
    # orderable) when two entries have equal cost.
    counter = itertools.count()
    frontier: list[tuple[float, int, State]] = [(0.0, next(counter), start)]

    while frontier:
        cost, _, state = heapq.heappop(frontier)
        if state in visited:
            continue
        visited.add(state)

        node, last_ride_route_id = state
        if node is DESTINATION:
            return SearchResult(
                total_duration_s=cost, edges=_reconstruct_edges(came_from, state)
            )

        for edge in adjacency.get(node, ()):
            new_cost = cost + edge_cost_fn(edge, last_ride_route_id)
            new_last_ride_route_id = (
                edge.route_id if edge.route_id is not None else last_ride_route_id
            )
            new_state: State = (edge.to_node, new_last_ride_route_id)

            if new_state in visited:
                continue
            if new_cost < dist.get(new_state, math.inf):
                dist[new_state] = new_cost
                came_from[new_state] = (state, edge)
                heapq.heappush(frontier, (new_cost, next(counter), new_state))

    return None
