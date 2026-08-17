"""
OSRM road-snapping for filling null `Route.path` geometry (plan.md
section D, Phase 3 - Route Geometry).

Only routes whose ordered `RouteStop` sequence has at least two stops,
*all* of which already have a coordinate (`Stop.location IS NOT NULL` -
i.e. Phase 2's geocoding pass, or the dataset's own SEED_DATUM stops,
resolved every one of them), are candidates here - see
`scripts/generate_route_geometry.py`'s `_eligible_routes`. A route with
even one unlocated stop is left completely untouched (`path` stays
whatever it was, `geometry_confidence` is not set to anything) rather
than generating a geometry that silently skips a stop.

`RouteGeometryProvider` is a small Protocol (the same shape as
`seeding.geocoding.Geocoder` / `ticketing.payments.provider.PaymentProvider`)
so tests and the CLI script can be exercised without any network access,
using a fake that returns canned results; `OSRMRouteGeometryProvider` is
the only real implementation, wrapping the public OSRM demo server's
`route` service.

This module never fabricates geometry: a route whose waypoints OSRM can't
connect (out of coverage, disconnected road graph, etc.) resolves to a
raised `RouteGeometryError` - the caller
(`scripts/generate_route_geometry.py`) leaves `Route.path` untouched and
records `geometry_confidence = "UNKNOWN"` rather than guessing a
straight-line polyline (the existing `simulation.engine` already falls
back to straight-line interpolation on its own when `path` is NULL - see
`docs/SIMULATION_DATA_SPEC.md` - so this module doesn't need to
materialize that fallback as data).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

# The public OSRM demo server (plan.md section D / section N): free, no
# API key, appropriate for a one-time build-time enrichment script - NOT
# for runtime per-request use (no SLA, may be slow or rate-limited). The
# documented production path is self-hosting OSRM against a Pakistan OSM
# extract (plan.md section D); nothing in this repository's runtime path
# calls this module today, only `scripts/generate_route_geometry.py`,
# invoked manually/offline.
OSRM_BASE_URL = "https://router.project-osrm.org"
USER_AGENT = "karwan-e-khizr-transit-route-geometry/1.0 (+backend/seeding/route_geometry.py)"

# A route needs at least two stops to have a "path" at all.
MIN_WAYPOINTS = 2


@dataclass(frozen=True)
class RouteGeometryResult:
    """One route's road-following geometry, from OSRM.

    `coordinates` is in GeoJSON/WKT order - (longitude, latitude) pairs,
    the *opposite* order from this project's usual (latitude, longitude)
    convention (`routing.geo.Point`, `api/transit/schemas.py`'s
    `Coordinates`) - because it is built directly from, and stored
    directly as, GeoJSON/WKT, both of which mandate (lon, lat).

    `leg_distances_m` has exactly `len(waypoints) - 1` entries: the road
    distance, in meters, from waypoint `i` to waypoint `i+1` as OSRM
    actually routed it (not the straight-line/Haversine distance) - the
    correct input for `RouteStop.distance_along_route_m` (a cumulative
    sum of these, see `cumulative_distances_m` below).
    """

    coordinates: tuple[tuple[float, float], ...]
    leg_distances_m: tuple[float, ...]


class RouteGeometryError(Exception):
    """OSRM couldn't produce a route through the given waypoints - either
    the HTTP request itself failed, or OSRM's own response reported
    anything other than success (e.g. `code != "Ok"`, or no route in the
    response). Distinct from "this route isn't eligible to try at all"
    (fewer than two located stops), which callers check before ever
    reaching this module."""


class RouteGeometryProvider(Protocol):
    """Interface a route-geometry backend (OSRM or a test fake) must
    satisfy."""

    async def route(
        self, waypoints: Sequence[tuple[float, float]]
    ) -> RouteGeometryResult:
        """`waypoints`: ordered (latitude, longitude) pairs, in the exact
        sequence the transit route visits them (never reordered - a
        transit route's stop order is fixed, unlike a delivery-style
        traveling-salesman problem). Must raise `RouteGeometryError`
        rather than fabricate a result if no route can be produced."""
        ...


def cumulative_distances_m(leg_distances_m: Sequence[float]) -> tuple[float, ...]:
    """Turn `RouteGeometryResult.leg_distances_m` (per-leg distances) into
    per-stop cumulative distances from the route's first stop - i.e.
    exactly what `RouteStop.distance_along_route_m` means. Always starts
    at 0.0 (the first stop is 0m from itself) and has one more entry than
    `leg_distances_m` (N legs connect N+1 stops)."""
    cumulative = [0.0]
    total = 0.0
    for leg in leg_distances_m:
        total += leg
        cumulative.append(total)
    return tuple(cumulative)


def linestring_wkt(coordinates: Sequence[tuple[float, float]]) -> str:
    """Build the `SRID=4326;LINESTRING(...)` WKT string
    `db.models.route.Route.path` (a GeoAlchemy2
    `Geometry(geometry_type="LINESTRING", srid=4326)` column) expects,
    from (longitude, latitude) pairs - the same "assign a WKT string
    directly to the mapped column" pattern already used for
    `Stop.location` in `seeding.importer._get_or_create_stop`."""
    points = ", ".join(f"{lon} {lat}" for lon, lat in coordinates)
    return f"SRID=4326;LINESTRING({points})"


class OSRMRouteGeometryProvider:
    """Real `RouteGeometryProvider`, wrapping OSRM's public `route`
    service (`driving` profile) with `overview=full&geometries=geojson`
    so the response is directly a GeoJSON `LineString` - snapped through
    every waypoint *in the given order* (OSRM's plain `route` service,
    not its `trip`/TSP service, which is free to reorder waypoints - not
    appropriate here since a transit route's stop sequence is fixed).

    Accepts an injected `httpx.AsyncClient` so tests can supply a
    `httpx.MockTransport`-backed client with no real network access; when
    none is given, this class owns and closes its own client.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        base_url: str = OSRM_BASE_URL,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=30.0
        )
        self._owns_client = client is None
        self._base_url = base_url

    async def __aenter__(self) -> "OSRMRouteGeometryProvider":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def route(
        self, waypoints: Sequence[tuple[float, float]]
    ) -> RouteGeometryResult:
        if len(waypoints) < MIN_WAYPOINTS:
            raise RouteGeometryError(
                f"need at least {MIN_WAYPOINTS} waypoints to route, got {len(waypoints)}"
            )

        # OSRM's coordinate order in the URL is (longitude, latitude),
        # the opposite of this function's own (latitude, longitude)
        # parameter order (see this module's docstring for why the two
        # conventions coexist).
        coord_path = ";".join(f"{lon},{lat}" for lat, lon in waypoints)
        url = f"{self._base_url}/route/v1/driving/{coord_path}"

        try:
            response = await self._client.get(
                url, params={"overview": "full", "geometries": "geojson"}
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise RouteGeometryError(f"OSRM request failed: {exc}") from exc

        if payload.get("code") != "Ok":
            raise RouteGeometryError(
                f"OSRM returned code={payload.get('code')!r}: {payload.get('message')!r}"
            )

        routes = payload.get("routes") or []
        if not routes:
            raise RouteGeometryError("OSRM response had no routes")

        best = routes[0]
        try:
            raw_coordinates = best["geometry"]["coordinates"]
            legs = best["legs"]
        except (KeyError, TypeError) as exc:
            raise RouteGeometryError(f"OSRM response missing expected fields: {exc}") from exc

        coordinates = tuple((float(lon), float(lat)) for lon, lat in raw_coordinates)
        leg_distances_m = tuple(float(leg["distance"]) for leg in legs)
        return RouteGeometryResult(coordinates=coordinates, leg_distances_m=leg_distances_m)
