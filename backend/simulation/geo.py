"""
Minimal, dependency-free geo primitives for the simulation subsystem.

Deliberately a separate, self-contained copy from `backend/routing/geo.py`
rather than importing it: the architectural requirement is that the
simulator be decoupled from the routing engine (routing must never import
the simulator, and this package shouldn't reach into `routing/` either -
see `simulation/__init__.py`), and both modules are small enough that
duplication is cheaper than coupling two independently-owned workstreams
together. If a genuinely shared geo-utilities module is ever justified,
that's a decision for whoever integrates all three workstreams, not this
one, unilaterally reaching into `backend/routing/` (a forbidden path for
this workstream).
"""

from __future__ import annotations

import math
from typing import NamedTuple

# Mean Earth radius in meters (WGS84 authalic radius) - same constant and
# rationale as `routing.geo._EARTH_RADIUS_M`.
_EARTH_RADIUS_M = 6_371_000.0


class Point(NamedTuple):
    """A WGS84 (SRID 4326) latitude/longitude pair."""

    latitude: float
    longitude: float


def haversine_distance_m(a: Point, b: Point) -> float:
    """Great-circle distance between two points, in meters.

    Used only to turn a route's stop coordinates into an assumed travel
    time when `RouteStop.distance_along_route_m` isn't populated (see
    `simulation.timing.compute_stop_time_offsets`) - not for the
    positional interpolation itself, which uses `interpolate_point` below.
    """
    lat1, lon1 = math.radians(a.latitude), math.radians(a.longitude)
    lat2, lon2 = math.radians(b.latitude), math.radians(b.longitude)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    h = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    central_angle = 2 * math.asin(math.sqrt(h))
    return _EARTH_RADIUS_M * central_angle


def interpolate_point(a: Point, b: Point, fraction: float) -> Point:
    """Linearly interpolate between two WGS84 points in lat/lon space.

    `fraction` is clamped to `[0, 1]` so a caller can never produce a
    point outside the `a`-to-`b` segment through a rounding error or an
    out-of-range input.

    **Documented simplification**: this is a straight-line interpolation
    across raw latitude/longitude, not a great-circle (spherical) slerp
    and not a real road path - a simulation approximation, same spirit as
    `routing.providers.StraightLineWalkingProvider`'s straight-line
    walking distance. At the short inter-stop distances this project
    deals with (a few hundred meters to a few kilometers), the difference
    between planar and great-circle interpolation is negligible; it would
    NOT be an acceptable approximation for e.g. transoceanic distances,
    which is irrelevant here. Do not use this for real road navigation -
    the task explicitly rules out adding an external routing service for
    that.
    """
    clamped_fraction = min(1.0, max(0.0, fraction))
    latitude = a.latitude + (b.latitude - a.latitude) * clamped_fraction
    longitude = a.longitude + (b.longitude - a.longitude) * clamped_fraction
    return Point(latitude=latitude, longitude=longitude)


def compute_bearing(a: Point, b: Point) -> float:
    """Initial great-circle bearing from `a` to `b`, in degrees clockwise
    from true north, normalized to `[0, 360)` (plan.md section G/H's
    `bearing` field - the direction a map client rotates a vehicle icon
    to face).

    For two identical points this is mathematically degenerate (there is
    no direction to face); the formula below naturally returns `0.0` in
    that case rather than raising, but callers that care about "no
    meaningful direction of travel" should decide that themselves from
    context (e.g. `simulation.engine.compute_position_at` only calls this
    when there IS a next stop to face, i.e. `next_stop_id is not None`)
    rather than relying on this function to signal it.
    """
    lat1, lon1 = math.radians(a.latitude), math.radians(a.longitude)
    lat2, lon2 = math.radians(b.latitude), math.radians(b.longitude)
    delta_lon = lon2 - lon1

    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(
        delta_lon
    )
    bearing_rad = math.atan2(x, y)
    return (math.degrees(bearing_rad) + 360.0) % 360.0


def _cumulative_distances_m(polyline: list[Point]) -> list[float]:
    """Running arc length (meters, via `haversine_distance_m`) up to and
    including each vertex of `polyline`. `cumulative[0] == 0.0`;
    `len(cumulative) == len(polyline)`."""
    cumulative = [0.0]
    for a, b in zip(polyline, polyline[1:]):
        cumulative.append(cumulative[-1] + haversine_distance_m(a, b))
    return cumulative


def _nearest_vertex_index(polyline: list[Point], point: Point) -> int:
    """Index of the vertex of `polyline` closest (straight-line) to
    `point`.

    **Documented simplification**: snaps to the nearest VERTEX of the
    polyline, not the nearest point on any of its segments. Acceptable at
    the vertex density OSRM's `overview=full` returns (routinely every
    few tens of meters - see `seeding.route_geometry`), the same spirit
    as `interpolate_point`'s own documented simplification above; a
    production-grade version would project onto segments instead.
    """
    return min(range(len(polyline)), key=lambda i: haversine_distance_m(polyline[i], point))


def point_along_polyline(
    polyline: list[Point], start: Point, end: Point, fraction: float
) -> tuple[Point, float] | None:
    """Interpolate `fraction` of the way from `start` to `end` by
    following the road-shaped `polyline` (e.g. a Route's OSRM-derived
    `path`, plan.md section D) instead of a straight line between them -
    used by `simulation.engine.compute_position_at` when a Route has real
    geometry, in place of `interpolate_point`.

    `start` and `end` are each snapped to their nearest polyline vertex
    (see `_nearest_vertex_index`), then the interpolated point is found
    by walking `fraction` of the arc length between those two vertices
    and locating which polyline segment that lands in.

    Returns `(point, bearing)` - `bearing` is the direction of the
    specific polyline segment the point falls on (via `compute_bearing`),
    which is more accurate than a straight `start`-to-`end` bearing on a
    curving road.

    Returns `None` - never a fabricated or wrong-direction point - when
    `end`'s nearest vertex is not strictly after `start`'s along
    `polyline` (e.g. the polyline doesn't actually run from `start` to
    `end` in that order, or the two stops snap to the same vertex).
    Callers must fall back to `interpolate_point`/straight-line behavior
    in that case, exactly as they already do when no polyline is
    supplied at all.
    """
    if len(polyline) < 2:
        return None

    cumulative = _cumulative_distances_m(polyline)
    start_index = _nearest_vertex_index(polyline, start)
    end_index = _nearest_vertex_index(polyline, end)
    if end_index <= start_index:
        return None

    start_s = cumulative[start_index]
    end_s = cumulative[end_index]
    if end_s <= start_s:
        return None

    clamped_fraction = min(1.0, max(0.0, fraction))
    target_s = start_s + clamped_fraction * (end_s - start_s)

    for i in range(start_index, end_index):
        if cumulative[i] <= target_s <= cumulative[i + 1]:
            segment_span = cumulative[i + 1] - cumulative[i]
            local_fraction = (
                (target_s - cumulative[i]) / segment_span if segment_span > 0 else 1.0
            )
            point = interpolate_point(polyline[i], polyline[i + 1], local_fraction)
            bearing = compute_bearing(polyline[i], polyline[i + 1])
            return point, bearing

    # Unreachable: target_s is clamped into [start_s, end_s] and the loop
    # above covers exactly that range - kept as a defensive fallback
    # (matches simulation.engine.compute_position_at's own
    # unreachable-guard convention) rather than silently returning
    # nothing useful if this invariant is ever violated.
    point = interpolate_point(polyline[start_index], polyline[end_index], 1.0)
    return point, compute_bearing(polyline[start_index], polyline[end_index])
