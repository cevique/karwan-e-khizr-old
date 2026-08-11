"""
Minimal shared geo primitives for the routing engine.

`Point` and `haversine_distance_m` are deliberately dependency-free (no
PostGIS/database access) and live outside `routing.graph`: they need to
work for *any* pair of WGS84 coordinates, including a mobile client's raw
origin/destination GPS point that has no corresponding `Stop` row at all
(the future origin/destination-snapping step) - not just for stops already
loaded from the database. `routing.graph`, `routing.providers`, and
`routing.ride_time` all import from here rather than each defining their
own point type or distance formula.
"""

from __future__ import annotations

import math
from typing import NamedTuple

# Mean Earth radius in meters (WGS84 authalic radius, standard for
# Haversine calculations).
_EARTH_RADIUS_M = 6_371_000.0


class Point(NamedTuple):
    """A WGS84 (SRID 4326) latitude/longitude pair - the same coordinate
    convention used everywhere else in this project (`Stop.location`,
    `api/transit/schemas.py`'s `Coordinates`)."""

    latitude: float
    longitude: float


def haversine_distance_m(a: Point, b: Point) -> float:
    """Great-circle distance between two points, in meters.

    Uses the Haversine formula (spherical-Earth approximation) rather than
    PostGIS's `ST_Distance` (which uses a more accurate ellipsoidal model)
    specifically because this function must also work for points that
    aren't in the database at all - see this module's docstring. At the
    short distances this project deals with (walking connections up to a
    few hundred meters; ride segments a few kilometers at most), the
    difference between spherical and ellipsoidal distance is on the order
    of centimeters to a few meters - negligible next to the fact that this
    whole approach is already a straight-line approximation of an actual
    walking/road route (see `routing.providers`'s module docstring).
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
