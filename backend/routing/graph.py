"""
In-memory routing graph: data structures and construction.

See README.md §13 "Route Planning Architecture". This module builds the
*static* part of the graph - Stops as nodes, plus two kinds of edges -
from the existing `Agency`/`Route`/`Stop`/`RouteStop` models:

- **Ride edges**: one directed edge per consecutive pair of stops in a
  Route's `RouteStop` sequence (`stop[i] -> stop[i+1]`). Each `Route` row
  represents one direction of travel (a return service is a separate
  `Route` row) - confirmed decision - so no reverse/bidirectional edges
  are synthesized here. Weighted (`duration_s`) via the injectable
  `ride_time_estimator` strategy (`routing.ride_time`, default
  `estimate_ride_time_seconds`).
- **Walking edges**: a directed edge between every pair of stops within
  `WALKING_RADIUS_M` of each other, in both directions, computed with a
  single PostGIS spatial self-join to find *which* pairs qualify
  (confirmed decision: precomputed once at graph-build time, not
  generated per search request - only origin/destination snapping, a
  later step, is per-request). Weighted (`distance_m`/`duration_s`) via
  the injectable `walking_provider` (`routing.providers`, default
  `StraightLineWalkingProvider`) - the provider, not this module, is the
  single source of truth for a walking edge's distance and duration, so
  swapping in a future real pedestrian-routing provider changes both
  values consistently without touching this file.

What this module still deliberately does NOT do (later, separate steps):
Dijkstra search and origin/destination snapping. Both `providers` and
`ride_time_estimator` parameters below default to the hackathon-
appropriate implementations, so existing callers (and Step 1's tests)
that don't pass them keep working unchanged.

The resulting `TransitGraph` is read-only (frozen dataclasses, tuples
instead of lists, `MappingProxyType` instead of plain dicts) so that the
cached-graph lifecycle planned for a later step (build once, reuse across
requests) can safely hand the same instance to concurrent requests without
any of them being able to mutate it.
"""

from __future__ import annotations

import decimal
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from types import MappingProxyType

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from db.models import Route, Stop
from routing.geo import Point
from routing.providers import StraightLineWalkingProvider, WalkingProvider
from routing.ride_time import estimate_ride_time_seconds

# Walking-edge search radius, in meters. README.md §13's Assumption A6
# default ("400m default"). Lives here (not yet in a shared
# `routing/config.py`) since this is currently its only user; move it once
# a second routing constant (e.g. a transfer penalty, in a later step)
# needs a shared home.
WALKING_RADIUS_M = 400.0

# Type of the injectable ride-time strategy - matches
# `routing.ride_time.estimate_ride_time_seconds`'s signature. Declared here
# (not in `routing.ride_time`) since it describes what *this module* needs
# from the strategy, not a property of the strategy itself.
RideTimeEstimator = Callable[
    [decimal.Decimal | None, decimal.Decimal | None, "GraphNode", "GraphNode"],
    float,
]


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
    are carried through as-is from `RouteStop` (not discarded once
    `duration_s` is computed) since a later step (e.g. a future schedule-
    aware search) may still want the raw sequence/distance data alongside
    the estimate. `duration_s` is computed once, at graph-build time, by
    the `ride_time_estimator` passed to `build_graph` (default:
    `routing.ride_time.estimate_ride_time_seconds`) - this dataclass
    itself has no estimation logic.
    """

    route_id: uuid.UUID
    agency_id: uuid.UUID
    from_stop_id: uuid.UUID
    to_stop_id: uuid.UUID
    from_sequence: int
    to_sequence: int
    from_distance_along_route_m: decimal.Decimal | None
    to_distance_along_route_m: decimal.Decimal | None
    duration_s: float


@dataclass(frozen=True)
class WalkEdge:
    """A directed walking edge between two stops within `WALKING_RADIUS_M`.

    Generated in both directions from a single undirected PostGIS radius
    query (see `_fetch_walking_pairs`, which now only determines *which*
    pairs qualify), since walking is symmetric but the graph's adjacency
    lookups (here and in later steps) are directional. Both `distance_m`
    and `duration_s` come from the `walking_provider` passed to
    `build_graph` (default: `StraightLineWalkingProvider`) - deliberately
    *not* PostGIS's own `ST_Distance` for the final stored value, so a
    single provider call is the sole source of truth for both fields
    together, avoiding two different distance figures disagreeing with
    each other if the provider is ever swapped for one with a different
    notion of "distance" (e.g. a real pedestrian-routing provider's path
    distance, which is not the same number as straight-line distance).
    """

    from_stop_id: uuid.UUID
    to_stop_id: uuid.UUID
    distance_m: float
    duration_s: float


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
    """Every Stop with coordinates, with those coordinates extracted via
    `ST_X`/`ST_Y` - the same pattern `api/transit/router.py` uses, for
    consistency (see that module's docstring for why: GeoAlchemy2 loads
    `Stop.location` as an opaque WKB element, so coordinates are extracted
    in SQL rather than in Python, avoiding a new dependency).

    `Stop.location` is nullable (Phase 1: ~105 of the canonical dataset's
    122 stops have no coordinates yet - see `docs/DATA_GAPS.md`), so stops
    without coordinates are filtered out here rather than becoming
    coordinate-less graph nodes. The graph simply has no node for a stop
    it can't position."""
    from geoalchemy2 import Geometry
    from sqlalchemy import cast

    longitude_expr = func.ST_X(cast(Stop.location, Geometry)).label("longitude")
    latitude_expr = func.ST_Y(cast(Stop.location, Geometry)).label("latitude")

    result = await session.execute(
        select(Stop, longitude_expr, latitude_expr).where(Stop.location.is_not(None))
    )
    return {
        stop.id: GraphNode(
            stop_id=stop.id, name=stop.name, latitude=latitude, longitude=longitude
        )
        for stop, longitude, latitude in result.all()
    }


async def _fetch_ride_edges(
    session: AsyncSession,
    nodes: Mapping[uuid.UUID, GraphNode],
    ride_time_estimator: RideTimeEstimator,
) -> tuple[RideEdge, ...]:
    """One directed edge per consecutive stop pair in each Route's
    `RouteStop` sequence, weighted via `ride_time_estimator`. Sorts each
    route's stops by `sequence` itself (rather than relying on
    `Route.route_stops`'s relationship-level `order_by`) so this
    function's correctness doesn't depend on a detail of another module's
    relationship configuration."""
    result = await session.execute(
        select(Route).options(selectinload(Route.route_stops))
    )
    routes = result.scalars().all()

    edges: list[RideEdge] = []
    for route in routes:
        ordered_route_stops = sorted(route.route_stops, key=lambda rs: rs.sequence)
        for current_rs, next_rs in pairwise(ordered_route_stops):
            # A stop whose coordinates aren't known yet (Stop.location is
            # nullable) has no graph node - the ride edge through it can't
            # be weighted, so it is skipped. Stops on either side of a gap
            # still connect across it (edge from the previous positioned
            # stop to the next positioned one) because each consecutive
            # pair is considered independently.
            if current_rs.stop_id not in nodes or next_rs.stop_id not in nodes:
                continue
            duration_s = ride_time_estimator(
                current_rs.distance_along_route_m,
                next_rs.distance_along_route_m,
                nodes[current_rs.stop_id],
                nodes[next_rs.stop_id],
            )
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
                    duration_s=duration_s,
                )
            )
    return tuple(edges)


async def _fetch_walking_pairs(
    session: AsyncSession,
) -> tuple[tuple[uuid.UUID, uuid.UUID], ...]:
    """Every unordered pair of distinct stops within `WALKING_RADIUS_M` of
    each other, via a single PostGIS spatial self-join (`StopA.id <
    StopB.id` keeps each pair to one row instead of two). Only determines
    *which* pairs qualify - the resulting pair's actual distance/duration
    comes from the injected `WalkingProvider` in `build_graph`, not from
    this query (see `WalkEdge`'s docstring for why)."""
    StopA = aliased(Stop)
    StopB = aliased(Stop)

    stmt = (
        select(StopA.id, StopB.id)
        .where(StopA.id < StopB.id)
        .where(func.ST_DWithin(StopA.location, StopB.location, WALKING_RADIUS_M))
    )
    result = await session.execute(stmt)
    return tuple(result.all())


async def build_graph(
    session: AsyncSession,
    *,
    walking_provider: WalkingProvider | None = None,
    ride_time_estimator: RideTimeEstimator | None = None,
) -> TransitGraph:
    """Build the complete static routing graph from the current database
    contents.

    `walking_provider` and `ride_time_estimator` default to the
    hackathon-appropriate implementations (`StraightLineWalkingProvider`,
    `estimate_ride_time_seconds`) when not given, so existing callers -
    including Step 1's tests, which call `build_graph(session)` with no
    extra arguments - keep working unchanged. Passing a different
    `WalkingProvider` (e.g. a future OSRM-backed one, or a test double) or
    a different ride-time strategy changes edge weighting without any
    other change to this function or to `TransitGraph`'s shape.

    Pure with respect to routing state: reads through the given session
    and provider/estimator, does not cache or mutate any module/global
    state, and returns a fresh, read-only `TransitGraph` every call - the
    *decision* of when to call this once and reuse the result (vs. call it
    fresh) belongs to a later "graph lifecycle" step, not to this function.
    """
    walking_provider = walking_provider or StraightLineWalkingProvider()
    ride_time_estimator = ride_time_estimator or estimate_ride_time_seconds

    nodes = await _fetch_nodes(session)
    ride_edges = await _fetch_ride_edges(session, nodes, ride_time_estimator)
    walking_pairs = await _fetch_walking_pairs(session)

    walk_edges_list: list[WalkEdge] = []
    for stop_a_id, stop_b_id in walking_pairs:
        node_a = nodes[stop_a_id]
        node_b = nodes[stop_b_id]
        estimate = await walking_provider.estimate_walk(
            Point(latitude=node_a.latitude, longitude=node_a.longitude),
            Point(latitude=node_b.latitude, longitude=node_b.longitude),
        )
        walk_edges_list.append(
            WalkEdge(
                from_stop_id=stop_a_id,
                to_stop_id=stop_b_id,
                distance_m=estimate.distance_m,
                duration_s=estimate.duration_s,
            )
        )
        walk_edges_list.append(
            WalkEdge(
                from_stop_id=stop_b_id,
                to_stop_id=stop_a_id,
                distance_m=estimate.distance_m,
                duration_s=estimate.duration_s,
            )
        )
    walk_edges = tuple(walk_edges_list)

    return TransitGraph(
        nodes=MappingProxyType(nodes),
        ride_edges=ride_edges,
        walk_edges=walk_edges,
        ride_edges_by_from=_group_by_from_stop(ride_edges, "from_stop_id"),
        walk_edges_by_from=_group_by_from_stop(walk_edges, "from_stop_id"),
    )
