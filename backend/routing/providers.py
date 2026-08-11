"""
Walking distance/time estimation.

We don't have a pedestrian road graph (README.md §13's walking-edge
description and this project's routing plan both note this explicitly).
`WalkingProvider` is the seam that keeps that limitation from leaking into
the rest of the routing engine: everything else in `routing` depends only
on this interface, never on `StraightLineWalkingProvider` specifically -
mirroring the `VehicleLocationProvider` replaceability pattern described
in README.md §14 for GPS (simulated now, official government API later).
A future `OSRMWalkingProvider` (or similar, calling a real pedestrian
routing engine/API) can be substituted here without any other routing code
changing.

`estimate_walk` is defined `async` even though the hackathon
implementation below does no I/O, specifically so that future
network-backed implementations (e.g. an HTTP call to OSRM) fit the same
interface without a breaking signature change later.
"""

from __future__ import annotations

from typing import NamedTuple, Protocol, runtime_checkable

from routing.geo import Point, haversine_distance_m

# README.md §13: "walking edges ... weighted by walking time at an assumed
# walking speed (~4.5 km/h)".
WALKING_SPEED_KMH = 4.5


class WalkEstimate(NamedTuple):
    """Result of a walking estimate between two points. A `NamedTuple` (not
    just a plain dataclass) so it also unpacks positionally as
    `(distance_m, duration_s)`, matching the routing plan's interface."""

    distance_m: float
    duration_s: float


def walking_duration_seconds(distance_m: float, speed_kmh: float = WALKING_SPEED_KMH) -> float:
    """Convert a distance into a walking duration at a constant speed.

    Factored out (rather than inlined into `StraightLineWalkingProvider`)
    so it's independently testable and reusable if a future provider needs
    "distance I already have -> duration" without recomputing distance.
    """
    if speed_kmh <= 0:
        raise ValueError("speed_kmh must be positive")
    speed_m_per_s = speed_kmh * 1000.0 / 3600.0
    return distance_m / speed_m_per_s


@runtime_checkable
class WalkingProvider(Protocol):
    """Interface for estimating the walking distance/time between two
    points. See this module's docstring for the replaceability rationale.
    """

    async def estimate_walk(self, origin: Point, destination: Point) -> WalkEstimate:
        """Estimate the walking distance and duration from `origin` to
        `destination`. Implementations should treat this as symmetric
        (`estimate_walk(a, b)` and `estimate_walk(b, a)` return the same
        result) unless there's a genuine reason a real provider wouldn't
        be (e.g. one-way pedestrian infrastructure) - `StraightLineWalkingProvider`
        below is symmetric by construction.
        """
        ...


class StraightLineWalkingProvider:
    """Hackathon-appropriate `WalkingProvider`: straight-line (great-circle)
    distance via `routing.geo.haversine_distance_m`, converted to a
    duration at a constant assumed walking speed.

    Known simplification (documented, not hidden): real walking distance
    around blocks/roads is always >= straight-line distance, so this
    under-estimates actual walking time - acceptable for a hackathon demo,
    same as the "simulated GPS" and "community-curated data" simplifications
    disclosed elsewhere in README.md, and specifically why this class
    exists behind the `WalkingProvider` interface rather than being used
    directly by the rest of the routing engine.
    """

    def __init__(self, speed_kmh: float = WALKING_SPEED_KMH) -> None:
        self._speed_kmh = speed_kmh

    async def estimate_walk(self, origin: Point, destination: Point) -> WalkEstimate:
        distance_m = haversine_distance_m(origin, destination)
        duration_s = walking_duration_seconds(distance_m, self._speed_kmh)
        return WalkEstimate(distance_m=distance_m, duration_s=duration_s)
