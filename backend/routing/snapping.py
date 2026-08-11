"""
Origin/destination-to-stop snapping.

Turns an arbitrary WGS84 point (a mobile client's raw origin or destination
GPS coordinate - not necessarily anywhere near an existing `Stop` row) into
a ranked list of nearby candidate stops, each with a walking distance and
duration, for a later step to splice into a per-request copy of the graph
as synthetic edges before running a search (README.md §13's "Snap to
nearby stops" step; this project's routing plan's "Origin/destination
handling" section).

This module intentionally does **not** import `routing.graph` or touch
`TransitGraph` at all: it only needs a database session, a point, and a
`WalkingProvider` - not the graph. That keeps the "never mutate the
cached/base `TransitGraph`" requirement trivially true here (there's
nothing to mutate), and leaves *how* a later search step combines these
connections with a `TransitGraph` copy entirely up to that step.

PostGIS query pattern: the same `ST_SetSRID(ST_MakePoint(lon, lat), 4326)`
-> `geography` + `ST_DWithin`/`ST_X`/`ST_Y` technique already used in
`api/transit/router.py`'s nearby-stops endpoint and `routing/graph.py`'s
walking-edge construction. Re-implemented here rather than imported from
either: `routing` must not depend on `api` (the API layer depends on
`routing`, never the reverse), and `routing/graph.py`'s equivalent helpers
are private to that module. `api/transit/router.py` already independently
re-implements this same pattern rather than importing it from anywhere
else, so doing the same here follows the codebase's existing precedent,
not a new one.

Distance/duration source of truth: exactly like `routing/graph.py`'s
walking edges (see that module's `WalkEdge` docstring), the *final*
distance and duration attached to each candidate come from the injected
`WalkingProvider`, not from PostGIS's `ST_Distance` - PostGIS is used only
to efficiently find *which* stops are within `max_walk_m` (a job only its
spatial index can do well at scale) and to get a reasonable initial
distance-based ordering/cap; the provider is the single source of truth
for the actual numbers, so swapping it (e.g. for a future real
pedestrian-routing provider) changes snapping results consistently with
every other walking estimate in the system.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from geoalchemy2 import Geography, Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Stop
from routing.geo import Point
from routing.providers import StraightLineWalkingProvider, WalkingProvider

# Origin/destination access radius default. Deliberately larger than
# routing.graph.WALKING_RADIUS_M (400m, the stop-to-stop transfer radius):
# a passenger has no choice but to walk from wherever they actually are,
# unlike an in-journey transfer where a shorter-radius alternative stop is
# usually available - see this project's routing plan's "Origin/
# destination handling" section. Still just a default: `snap_origin`/
# `snap_destination` accept a per-request override (the request's
# configurable `max_walk_m`, per this step's requirements) - a future API
# layer is expected to pass the client's value through here.
DEFAULT_MAX_WALK_M = 800.0

# Defensive cap on how many candidate stops a single snap query returns,
# nearest first. A passenger doesn't need dozens of boarding-stop options;
# this just bounds worst-case work (walking-provider calls, and later,
# synthetic-edge construction) in an unusually stop-dense area.
MAX_SNAP_CANDIDATES = 20


@dataclass(frozen=True)
class SnapCandidate:
    """A single candidate stop near a query point, with its walking
    distance/duration from that point (from the `WalkingProvider`, not
    PostGIS - see this module's docstring)."""

    stop_id: uuid.UUID
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class OriginConnection:
    """A directed synthetic walking connection: a query-time origin point
    -> a nearby `Stop`. Analogous to `routing.graph.WalkEdge`, except one
    end is a virtual point with no `Stop` row/graph node of its own -
    that's exactly why this is its own type rather than reusing `WalkEdge`.
    """

    to_stop_id: uuid.UUID
    distance_m: float
    duration_s: float


@dataclass(frozen=True)
class DestinationConnection:
    """A directed synthetic walking connection: a nearby `Stop` -> a
    query-time destination point. See `OriginConnection`'s docstring."""

    from_stop_id: uuid.UUID
    distance_m: float
    duration_s: float


async def _fetch_candidate_rows(
    session: AsyncSession, point: Point, max_walk_m: float
) -> tuple[tuple[uuid.UUID, float, float], ...]:
    """Every Stop within `max_walk_m` meters of `point`, nearest first
    (PostGIS spatial index via `ST_DWithin`, ordered/capped via
    `ST_Distance`), with each stop's own coordinates extracted in the same
    query (`ST_X`/`ST_Y`, same pattern as `api/transit/router.py` and
    `routing/graph.py` - see this module's docstring for why it's
    duplicated here rather than imported).
    """
    search_point = cast(
        func.ST_SetSRID(func.ST_MakePoint(point.longitude, point.latitude), 4326),
        Geography,
    )
    distance_expr = func.ST_Distance(Stop.location, search_point)
    longitude_expr = func.ST_X(cast(Stop.location, Geometry))
    latitude_expr = func.ST_Y(cast(Stop.location, Geometry))

    stmt = (
        select(Stop.id, longitude_expr, latitude_expr)
        .where(func.ST_DWithin(Stop.location, search_point, max_walk_m))
        .order_by(distance_expr)
        .limit(MAX_SNAP_CANDIDATES)
    )
    result = await session.execute(stmt)
    return tuple(result.all())


async def find_nearby_stops(
    session: AsyncSession,
    point: Point,
    max_walk_m: float = DEFAULT_MAX_WALK_M,
    *,
    walking_provider: WalkingProvider | None = None,
) -> tuple[SnapCandidate, ...]:
    """Find candidate stops near an arbitrary point, nearest first.

    Returns an empty tuple - not an exception - when no stop is within
    `max_walk_m` of `point`: "no candidates" is a normal, valid outcome of
    a spatial query, not an error condition. This is a plain routing-layer
    function with no HTTP awareness (`routing` must not depend on `api`),
    so it deliberately doesn't raise an HTTP-flavored error here; deciding
    how an empty result becomes e.g. a 404 is a future API step's job.

    `walking_provider` defaults to `StraightLineWalkingProvider()` when not
    given, matching `routing.graph.build_graph`'s same pattern, so the
    default is always usable without extra wiring while remaining fully
    substitutable (e.g. for a future real pedestrian-routing provider, or a
    test double).
    """
    walking_provider = walking_provider or StraightLineWalkingProvider()

    rows = await _fetch_candidate_rows(session, point, max_walk_m)
    if not rows:
        return ()

    candidates = []
    for stop_id, longitude, latitude in rows:
        estimate = await walking_provider.estimate_walk(
            point, Point(latitude=latitude, longitude=longitude)
        )
        candidates.append(
            SnapCandidate(
                stop_id=stop_id,
                distance_m=estimate.distance_m,
                duration_s=estimate.duration_s,
            )
        )

    # Re-sort by the provider's own distance rather than trusting the SQL
    # query's ST_Distance-based order: the provider is the source of truth
    # for the returned distance (see module docstring), so the *returned*
    # order should match it too, even though in practice the two orderings
    # coincide almost always at these short distances.
    candidates.sort(key=lambda c: c.distance_m)
    return tuple(candidates)


async def snap_origin(
    session: AsyncSession,
    origin: Point,
    max_walk_m: float = DEFAULT_MAX_WALK_M,
    *,
    walking_provider: WalkingProvider | None = None,
) -> tuple[OriginConnection, ...]:
    """Candidate boarding stops near an arbitrary origin point, as directed
    `origin -> stop` synthetic connections, nearest first."""
    candidates = await find_nearby_stops(
        session, origin, max_walk_m, walking_provider=walking_provider
    )
    return tuple(
        OriginConnection(
            to_stop_id=c.stop_id, distance_m=c.distance_m, duration_s=c.duration_s
        )
        for c in candidates
    )


async def snap_destination(
    session: AsyncSession,
    destination: Point,
    max_walk_m: float = DEFAULT_MAX_WALK_M,
    *,
    walking_provider: WalkingProvider | None = None,
) -> tuple[DestinationConnection, ...]:
    """Candidate alighting stops near an arbitrary destination point, as
    directed `stop -> destination` synthetic connections, nearest first."""
    candidates = await find_nearby_stops(
        session, destination, max_walk_m, walking_provider=walking_provider
    )
    return tuple(
        DestinationConnection(
            from_stop_id=c.stop_id, distance_m=c.distance_m, duration_s=c.duration_s
        )
        for c in candidates
    )
