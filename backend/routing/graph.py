"""
In-memory routing graph: data structures and construction.

See README.md §13 "Route Planning Architecture". This module builds the
*static* part of the graph - Stops as nodes, plus two kinds of edges -
from the existing `Agency`/`Route`/`Stop`/`RouteStop` models:

- **Ride edges**: one directed edge per consecutive pair of stops in a
  Route's `RouteStop` sequence (`stop[i] -> stop[i+1]`). Each `Route` row
  represents one direction of travel (a return service is a separate
  `Route` row) - confirmed decision - so no reverse/bidirectional edges
  are synthesized here.
- **Walking edges**: a directed edge between every pair of stops within
  `WALKING_RADIUS_M` of each other, in both directions, computed with a
  single PostGIS spatial self-join (confirmed decision: precomputed once
  at graph-build time, not generated per search request - only
  origin/destination snapping, a later step, is per-request).

What this module deliberately does NOT do yet (later, separate steps):
edge *weights* (ride/walking time estimates - see the planned
`WalkingProvider` / `estimate_ride_time` seam), Dijkstra search, and
origin/destination snapping. `RideEdge`/`WalkEdge` here carry only the raw
structural data (sequence positions, `distance_along_route_m`, straight-
line `distance_m`) that a later weighting step will need - no `weight` or
`duration_s` field exists yet, so there's nothing to get wrong before that
design is actually implemented.

The resulting `TransitGraph` is read-only (frozen dataclasses, tuples
instead of lists, `MappingProxyType` instead of plain dicts) so that the
cached-graph lifecycle planned for a later step (build once, reuse across
requests) can safely hand the same instance to concurrent requests without
any of them being able to mutate it.
"""

from __future__ import annotations

import decimal
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from db.models import Route, Stop

# Walking-edge search radius, in meters. README.md §13's Assumption A6
# default ("400m default"). Lives here (not yet in a shared
# `routing/config.py`) since this is currently its only user; move it once
# a second routing constant (e.g. a transfer penalty, in a later step)
# needs a shared home.
WALKING_RADIUS_M = 400.0


@dataclass(frozen=True)
class GraphNode:
    """A single Stop, as a routing-graph node.

    Carries latitude/longitude (extracted once here, the same way
    `api/transit/router.py` extracts them for API responses) since nearly
    every later step - edge weighting, origin/destination snapping, a
    possible future A* heuristic - needs a stop's coordinates, and this
    avoids every one of those steps re-querying PostGIS for the same
    values.
    """

    stop_id: uuid.UUID
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class RideEdge:
    """A directed edge from one stop to the next stop on the same Route.

    `from_sequence`/`to_sequence` and the `distance_along_route_m` values
    are carried through as-is from `RouteStop` (not combined into a single
    weight) - a later step's ride-time estimator computes an actual weight
    from these; this dataclass only records the graph structure.
    """

    route_id: uuid.UUID
    agency_id: uuid.UUID
    from_stop_id: uuid.UUID
    to_stop_id: uuid.UUID
    from_sequence: int
    to_sequence: int
    from_distance_along_route_m: decimal.Decimal | None
    to_distance_along_route_m: decimal.Decimal | None


@dataclass(frozen=True)
class WalkEdge:
    """A directed walking edge between two stops within `WALKING_RADIUS_M`.

    Generated in both directions from a single undirected PostGIS pair
    query (see `_fetch_walking_pairs`), since walking is symmetric but the
    graph's adjacency lookups (here and in later steps) are directional.
    `distance_m` is the straight-line PostGIS distance; converting it into
    a walking *time* is the `WalkingProvider` interface's job, a later
    step - not this one.
    """

    from_stop_id: uuid.UUID
    to_stop_id: uuid.UUID
    distance_m: float


@dataclass(frozen=True)
class TransitGraph:
    """The complete static routing graph: every Stop, every ride edge, and
    every precomputed walking edge, plus from-stop adjacency indexes for
    O(1) traversal lookups.

    Read-only by construction: all containers are immutable
    (`MappingProxyType`/tuples), so this instance is safe to share across
    concurrent requests once a later step caches it (README §13: "rebuilt
    periodically... and cached in memory").
    """

    nodes: Mapping[uuid.UUID, GraphNode]
    ride_edges: tuple[RideEdge, ...]
    walk_edges: tuple[WalkEdge, ...]
    ride_edges_by_from: Mapping[uuid.UUID, tuple[RideEdge, ...]]
    walk_edges_by_from: Mapping[uuid.UUID, tuple[WalkEdge, ...]]


def _group_by_from_stop(
    edges: tuple, from_attr: str
) -> Mapping[uuid.UUID, tuple]:
    """Group a tuple of ride/walk edges by their `from_stop_id`, returning
    a read-only mapping to a read-only tuple of edges for that stop."""
    grouped: dict[uuid.UUID, list] = {}
    for edge in edges:
        grouped.setdefault(getattr(edge, from_attr), []).append(edge)
    return MappingProxyType(
        {stop_id: tuple(group) for stop_id, group in grouped.items()}
    )


async def _fetch_nodes(session: AsyncSession) -> dict[uuid.UUID, GraphNode]:
    """Every Stop, with its coordinates extracted via `ST_X`/`ST_Y` - the
    same pattern `api/transit/router.py` uses, for consistency (see that
    module's docstring for why: GeoAlchemy2 loads `Stop.location` as an
    opaque WKB element, so coordinates are extracted in SQL rather than in
    Python, avoiding a new dependency)."""
    from geoalchemy2 import Geometry
    from sqlalchemy import cast

    longitude_expr = func.ST_X(cast(Stop.location, Geometry)).label("longitude")
    latitude_expr = func.ST_Y(cast(Stop.location, Geometry)).label("latitude")

    result = await session.execute(select(Stop, longitude_expr, latitude_expr))
    return {
        stop.id: GraphNode(
            stop_id=stop.id, name=stop.name, latitude=latitude, longitude=longitude
        )
        for stop, longitude, latitude in result.all()
    }


async def _fetch_ride_edges(session: AsyncSession) -> tuple[RideEdge, ...]:
    """One directed edge per consecutive stop pair in each Route's
    `RouteStop` sequence. Sorts each route's stops by `sequence` itself
    (rather than relying on `Route.route_stops`'s relationship-level
    `order_by`) so this function's correctness doesn't depend on a detail
    of another module's relationship configuration."""
    result = await session.execute(
        select(Route).options(selectinload(Route.route_stops))
    )
    routes = result.scalars().all()

    edges: list[RideEdge] = []
    for route in routes:
        ordered_route_stops = sorted(route.route_stops, key=lambda rs: rs.sequence)
        for current_rs, next_rs in pairwise(ordered_route_stops):
            edges.append(
                RideEdge(
                    route_id=route.id,
                    agency_id=route.agency_id,
                    from_stop_id=current_rs.stop_id,
                    to_stop_id=next_rs.stop_id,
                    from_sequence=current_rs.sequence,
                    to_sequence=next_rs.sequence,
                    from_distance_along_route_m=current_rs.distance_along_route_m,
                    to_distance_along_route_m=next_rs.distance_along_route_m,
                )
            )
    return tuple(edges)


async def _fetch_walking_pairs(
    session: AsyncSession,
) -> tuple[tuple[uuid.UUID, uuid.UUID, float], ...]:
    """Every unordered pair of distinct stops within `WALKING_RADIUS_M` of
    each other, via a single PostGIS spatial self-join (`StopA.id <
    StopB.id` keeps each pair to one row instead of two)."""
    StopA = aliased(Stop)
    StopB = aliased(Stop)

    distance_expr = func.ST_Distance(StopA.location, StopB.location)

    stmt = (
        select(StopA.id, StopB.id, distance_expr)
        .where(StopA.id < StopB.id)
        .where(func.ST_DWithin(StopA.location, StopB.location, WALKING_RADIUS_M))
    )
    result = await session.execute(stmt)
    return tuple(result.all())


async def build_graph(session: AsyncSession) -> TransitGraph:
    """Build the complete static routing graph from the current database
    contents.

    Pure with respect to routing state: reads through the given session,
    does not cache or mutate any module/global state, and returns a fresh,
    read-only `TransitGraph` every call - the *decision* of when to call
    this once and reuse the result (vs. call it fresh) belongs to a later
    "graph lifecycle" step, not to this function.
    """
    nodes = await _fetch_nodes(session)
    ride_edges = await _fetch_ride_edges(session)
    walking_pairs = await _fetch_walking_pairs(session)

    walk_edges = tuple(
        walk_edge
        for stop_a_id, stop_b_id, distance_m in walking_pairs
        for walk_edge in (
            WalkEdge(
                from_stop_id=stop_a_id, to_stop_id=stop_b_id, distance_m=distance_m
            ),
            WalkEdge(
                from_stop_id=stop_b_id, to_stop_id=stop_a_id, distance_m=distance_m
            ),
        )
    )

    return TransitGraph(
        nodes=MappingProxyType(nodes),
        ride_edges=ride_edges,
        walk_edges=walk_edges,
        ride_edges_by_from=_group_by_from_stop(ride_edges, "from_stop_id"),
        walk_edges_by_from=_group_by_from_stop(walk_edges, "from_stop_id"),
    )
