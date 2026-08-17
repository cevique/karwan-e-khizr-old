#!/usr/bin/env python3
"""
Generate road-following `Route.path` geometry via OSRM road-snapping
(Phase 3 of `plan.md`, section D).

Run from the `backend/` directory, against the database configured by
`DATABASE_URL`:

    python scripts/generate_route_geometry.py                # every eligible route
    python scripts/generate_route_geometry.py --dry-run       # look up geometry, write nothing
    python scripts/generate_route_geometry.py --limit 5       # only the first 5 eligible routes

A route is **eligible** only when its ordered `RouteStop` sequence has at
least two stops and *every one* of them already has a coordinate (i.e.
Phase 1's SEED_DATUM stops and/or Phase 2's `scripts/geocode_stops.py`
resolved them all - see `docs/DATA_GAPS.md`). A route with even one
unlocated stop in its sequence is skipped entirely and left completely
untouched: `Route.path`/`geometry_source`/`geometry_confidence` stay
whatever they already were. This is deliberate - generating a geometry
that silently omits an unlocated stop would misrepresent the route's real
path, and "not yet attempted" must stay distinguishable from "attempted
and failed" (see `seeding.route_geometry`'s module docstring).

For each eligible route, in stop order (never reordered - see
`seeding.route_geometry.OSRMRouteGeometryProvider`'s docstring):

  - a successful OSRM road-snap ->
      `Route.path`                       = the returned LineString (WKT)
      `Route.geometry_source`            = "OSRM"
      `Route.geometry_confidence`        = "OSM-DERIVED"
      `RouteStop.distance_along_route_m` = cumulative OSRM leg distance
                                            to that stop (see
                                            `seeding.route_geometry.cumulative_distances_m`)
  - a failure (HTTP/network error, or OSRM reports no route) ->
      `Route.path` is left untouched (never cleared)
      `Route.geometry_confidence`        = "UNKNOWN" (attempted, failed)
      (`Route.geometry_source` is left untouched too - nothing was
      actually sourced, mirroring `scripts/geocode_stops.py`'s handling
      of `Stop.coordinate_source` on a failed geocode)

Requires outbound network access to `router.project-osrm.org`; a
sandboxed environment with restricted egress will need to run this from
somewhere that has it (same caveat as `scripts/geocode_stops.py`).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

logger = logging.getLogger("generate_route_geometry")


async def _eligible_routes(session, limit: int | None = None):
    """Return `[(route, ordered_route_stops, waypoints), ...]` for every
    Route eligible for geometry generation (see this module's docstring),
    ordered by `short_name` for determinism, capped at `limit` if given.

    `waypoints` is `[(latitude, longitude), ...]` in the route's own
    stop order - the shape `RouteGeometryProvider.route()` expects.
    Coordinates are extracted via `ST_X`/`ST_Y` rather than through the
    ORM (see `api/transit/router.py`'s module docstring for why this
    project always extracts `Stop.location` that way).
    """
    from geoalchemy2 import Geometry
    from sqlalchemy import cast, select
    from sqlalchemy import func as sa_func
    from sqlalchemy.orm import selectinload

    from db.models import Route, RouteStop, Stop

    routes = (
        await session.execute(
            select(Route)
            .options(selectinload(Route.route_stops).selectinload(RouteStop.stop))
            .order_by(Route.short_name)
        )
    ).scalars().all()

    eligible: list[tuple[Route, list[RouteStop], list[tuple[float, float]]]] = []
    for route in routes:
        ordered = sorted(route.route_stops, key=lambda rs: rs.sequence)
        if len(ordered) < 2:
            continue

        stop_ids = [rs.stop_id for rs in ordered]
        coord_rows = (
            await session.execute(
                select(
                    Stop.id,
                    sa_func.ST_X(cast(Stop.location, Geometry)),
                    sa_func.ST_Y(cast(Stop.location, Geometry)),
                ).where(Stop.id.in_(stop_ids))
            )
        ).all()
        coords_by_stop_id = {sid: (lon, lat) for sid, lon, lat in coord_rows}

        if any(coords_by_stop_id.get(sid, (None, None))[0] is None for sid in stop_ids):
            continue  # at least one stop on this route has no coordinate yet

        waypoints = [
            (coords_by_stop_id[sid][1], coords_by_stop_id[sid][0]) for sid in stop_ids
        ]
        eligible.append((route, ordered, waypoints))
        if limit is not None and len(eligible) >= limit:
            break

    return eligible


async def generate_route_geometry(
    session,
    provider,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Core logic, deliberately taking a plain `AsyncSession` and a
    `seeding.route_geometry.RouteGeometryProvider` rather than
    importing/constructing them itself - lets tests pass a rolled-back
    test session and a fake provider with no real database commit or
    network access, while `main()` below wires up the real ones (mirrors
    `scripts.geocode_stops.geocode_null_coordinate_stops`).

    Returns `{"eligible": ..., "generated": ..., "failed": ...}`.
    """
    from seeding.route_geometry import (
        RouteGeometryError,
        cumulative_distances_m,
        linestring_wkt,
    )

    candidates = await _eligible_routes(session, limit)

    generated = 0
    failed = 0
    for route, ordered, waypoints in candidates:
        try:
            result = await provider.route(waypoints)
        except RouteGeometryError as exc:
            failed += 1
            logger.info("no geometry for %-10s : %s", route.short_name, exc)
            if not dry_run:
                route.geometry_confidence = "UNKNOWN"
            continue

        generated += 1
        total_m = sum(result.leg_distances_m)
        logger.info(
            "generated geometry for %-10s : %d points, %.0fm total",
            route.short_name,
            len(result.coordinates),
            total_m,
        )
        if not dry_run:
            route.path = linestring_wkt(result.coordinates)
            route.geometry_source = "OSRM"
            route.geometry_confidence = "OSM-DERIVED"
            for route_stop, distance_m in zip(
                ordered, cumulative_distances_m(result.leg_distances_m)
            ):
                route_stop.distance_along_route_m = distance_m

    if not dry_run:
        await session.commit()

    return {"eligible": len(candidates), "generated": generated, "failed": failed}


async def _run(args: argparse.Namespace) -> None:
    from db.session import AsyncSessionLocal
    from seeding.route_geometry import OSRMRouteGeometryProvider

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    async with AsyncSessionLocal() as session:
        async with OSRMRouteGeometryProvider() as provider:
            stats = await generate_route_geometry(
                session, provider, dry_run=args.dry_run, limit=args.limit
            )

    print(f"eligible routes (>=2 stops, all located): {stats['eligible']}")
    print(f"geometry generated (OSRM/OSM-DERIVED):     {stats['generated']}")
    print(f"failed (UNKNOWN):                          {stats['failed']}")
    if args.dry_run:
        print("Dry run: nothing written.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Look up geometry and print it, but write nothing to the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N eligible routes (by short_name). Useful for a smoke test.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
