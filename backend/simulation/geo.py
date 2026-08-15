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
