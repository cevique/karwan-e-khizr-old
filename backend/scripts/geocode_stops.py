#!/usr/bin/env python3
"""
Fill null `Stop.location` coordinates via OpenStreetMap Nominatim
geocoding (Phase 2 of `plan.md`, section C).

Run from the `backend/` directory, against the database configured by
`DATABASE_URL`:

    python scripts/geocode_stops.py                # geocode every null-coordinate stop
    python scripts/geocode_stops.py --dry-run       # look up matches, write nothing
    python scripts/geocode_stops.py --limit 10      # only the first 10 (useful for a smoke test)

Only stops with `location IS NULL` are ever queried; stops that already
have coordinates (the 17 SEED_DATUM rows imported from
`docs/transit_data.json` in Phase 1) are never touched or overwritten -
plan.md section C: "Do NOT overwrite coordinates that already exist -
only fill nulls." For each candidate stop, both query variants
(Islamabad then Rawalpindi - see `seeding.geocoding.query_variants`) are
tried in order:

  - an in-bounds match ->
      `location`               = the matched point
      `coordinate_source`      = "NOMINATIM"
      `coordinate_confidence`  = "APPROXIMATE"
  - no in-bounds match for either variant ->
      `location` stays NULL
      `coordinate_confidence`  = "UNKNOWN"
      (`coordinate_source` stays NULL - nothing was actually sourced)

Nominatim's usage policy caps this at 1 request/second (enforced by
`seeding.geocoding.NominatimGeocoder`), and up to two requests are made
per stop, so ~105 stops takes on the order of a few minutes. Requires
outbound network access to `nominatim.openstreetmap.org`; a sandboxed
environment with restricted egress will need to run this from somewhere
that has it (see the Phase 2 handoff note in `plan.md`).
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

logger = logging.getLogger("geocode_stops")


async def geocode_null_coordinate_stops(
    session,
    geocoder,
    *,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """Core logic, deliberately taking a plain `AsyncSession` and a
    `seeding.geocoding.Geocoder` rather than importing/constructing them
    itself - lets tests pass a rolled-back test session and a fake
    geocoder with no real database commit or network access, while
    `main()` below wires up the real ones.

    Returns `{"total": ..., "geocoded": ..., "unresolved": ...}`.
    """
    from sqlalchemy import select

    from db.models import Stop
    from seeding.geocoding import geocode_stop_name

    stmt = select(Stop).where(Stop.location.is_(None)).order_by(Stop.name)
    if limit is not None:
        stmt = stmt.limit(limit)
    stops = list((await session.execute(stmt)).scalars())

    geocoded = 0
    unresolved = 0
    for stop in stops:
        result = await geocode_stop_name(geocoder, stop.name)
        if result is not None:
            geocoded += 1
            logger.info(
                "geocoded %-30s -> (%.5f, %.5f)  %s",
                stop.name,
                result.latitude,
                result.longitude,
                result.display_name,
            )
            if not dry_run:
                stop.location = f"SRID=4326;POINT({result.longitude} {result.latitude})"
                stop.coordinate_source = "NOMINATIM"
                stop.coordinate_confidence = "APPROXIMATE"
        else:
            unresolved += 1
            logger.info("no in-bounds match for %s", stop.name)
            if not dry_run:
                stop.coordinate_confidence = "UNKNOWN"

    if not dry_run:
        await session.commit()

    return {"total": len(stops), "geocoded": geocoded, "unresolved": unresolved}


async def _run(args: argparse.Namespace) -> None:
    from db.session import AsyncSessionLocal
    from seeding.geocoding import NominatimGeocoder

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    async with AsyncSessionLocal() as session:
        async with NominatimGeocoder() as geocoder:
            stats = await geocode_null_coordinate_stops(
                session, geocoder, dry_run=args.dry_run, limit=args.limit
            )

    print(f"null-coordinate stops examined:    {stats['total']}")
    print(f"geocoded (NOMINATIM/APPROXIMATE):  {stats['geocoded']}")
    print(f"unresolved (UNKNOWN):              {stats['unresolved']}")
    if args.dry_run:
        print("Dry run: nothing written.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Look up matches and print them, but write nothing to the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N null-coordinate stops (by name). Useful for a smoke test.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
