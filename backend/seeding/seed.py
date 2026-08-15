"""
Apply, reset, and inspect the deterministic demo dataset defined in
`data.seed_dataset` against the real database.

See `data/seed_dataset.py`'s module docstring for why every seeded row
gets a deterministic UUID (`uuid.uuid5`-derived from a stable key) instead
of a random one - that's what makes both operations below safe:

- `seed_database` can tell "already seeded" from "not seeded yet" without
  a side table, by simply checking whether a row with that exact ID
  already exists.
- `clear_seed_data` can delete precisely the rows this dataset owns (by
  ID) and nothing else, however much unrelated data (from imports, from
  Claude A/B's own workstreams once merged, ...) also happens to be in
  the same tables.

Framework-agnostic on purpose (no FastAPI import here): takes a plain
`AsyncSession` so it can be driven from the admin API, a standalone
script, or a test, identically.
"""

from __future__ import annotations

import dataclasses
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from data.seed_dataset import (
    SEED_AGENCIES,
    SEED_ROUTES,
    SEED_STOPS,
    agency_id,
    route_id,
    route_stop_id,
    stop_id,
)
from db.models import Agency, Route, RouteStop, Stop
from seeding.import_schema import (
    ImportAgency,
    ImportDataset,
    ImportRoute,
    ImportRouteStop,
    ImportStop,
)

VALID_SEED_MODES = ("insert", "replace")


def seed_dataset_as_import_dataset() -> ImportDataset:
    """Re-express `data.seed_dataset`'s dataset as a plain
    `ImportDataset`, so `seeding.validation.validate_dataset` can be run
    against it directly - a cheap sanity check ("is the demo dataset
    itself internally consistent") reused by both the dev API's
    `/dev/validate/seed` endpoint and this package's own tests. Never
    used for actual seeding (`seed_database` above works from
    `data.seed_dataset` directly, via deterministic IDs, not through
    this ref-based shape).
    """
    return ImportDataset(
        agencies=tuple(
            ImportAgency(name=a.name, network_type=a.network_type)
            for a in SEED_AGENCIES
        ),
        stops=tuple(
            ImportStop(ref=s.key, name=s.name, latitude=s.latitude, longitude=s.longitude)
            for s in SEED_STOPS
        ),
        routes=tuple(
            ImportRoute(
                ref=r.key,
                agency=next(a.name for a in SEED_AGENCIES if a.key == r.agency_key),
                short_name=r.short_name,
                long_name=r.long_name,
                color=r.color,
            )
            for r in SEED_ROUTES
        ),
        route_stops=tuple(
            ImportRouteStop(route_ref=r.key, stop_ref=stop_key, sequence=sequence)
            for r in SEED_ROUTES
            for sequence, stop_key in enumerate(r.stop_keys, start=1)
        ),
    )


@dataclasses.dataclass
class SeedReport:
    """Outcome of one `seed_database` call. Every count reflects rows
    actually created or left alone during *this* call - not the total
    size of the dataset (see `get_seed_status` for that)."""

    mode: str
    agencies_created: int = 0
    agencies_skipped: int = 0
    stops_created: int = 0
    stops_skipped: int = 0
    routes_created: int = 0
    routes_skipped: int = 0
    route_stops_created: int = 0
    route_stops_skipped: int = 0


def _all_seed_agency_ids() -> list[uuid.UUID]:
    return [agency_id(a.key) for a in SEED_AGENCIES]


def _all_seed_stop_ids() -> list[uuid.UUID]:
    return [stop_id(s.key) for s in SEED_STOPS]


async def clear_seed_data(session: AsyncSession) -> None:
    """Delete exactly the rows this dataset owns, by their deterministic
    IDs - never a blanket "delete everything" in these tables.

    Deleting the seed Agencies cascades (ON DELETE CASCADE, enforced at
    the database level by the existing FK constraints - see
    `db/models/route.py` and `db/models/route_stop.py`) to their seed
    Routes and those Routes' RouteStops. Deleting the seed Stops
    separately then cascades away any remaining RouteStop rows that
    reference them (e.g. a feeder route owned by a *different* seed
    agency that also stops at a seed Stop). Plain Core
    `DELETE ... WHERE id IN (...)` statements are used (the same pattern
    this project's own `tests/test_graph_state.py` already uses for
    cleanup) rather than loading ORM objects and calling
    `session.delete()`, since the goal is exactly "remove these known
    rows by ID", not walking in-memory relationships.

    This is a DESTRUCTIVE, development-only operation. It is exposed
    through the admin API's `/admin/seed/reset` endpoint, which is not
    registered on the main application router (see `api/admin/router.py`
    module docstring) - callers must wire it up deliberately.
    """
    await session.execute(
        sa.delete(Agency).where(Agency.id.in_(_all_seed_agency_ids()))
    )
    await session.execute(sa.delete(Stop).where(Stop.id.in_(_all_seed_stop_ids())))
    await session.commit()


async def get_seed_status(session: AsyncSession) -> dict[str, int]:
    """How much of the seed dataset is currently present in the database,
    counted by deterministic ID membership - not by name matching or row
    count of the whole table (which could include unrelated data)."""
    agencies_present = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(Agency)
            .where(Agency.id.in_(_all_seed_agency_ids()))
        )
    ).scalar_one()
    stops_present = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(Stop)
            .where(Stop.id.in_(_all_seed_stop_ids()))
        )
    ).scalar_one()
    routes_present = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(Route)
            .where(Route.id.in_([route_id(r.key) for r in SEED_ROUTES]))
        )
    ).scalar_one()

    return {
        "seed_agencies_present": agencies_present,
        "seed_agencies_total": len(SEED_AGENCIES),
        "seed_stops_present": stops_present,
        "seed_stops_total": len(SEED_STOPS),
        "seed_routes_present": routes_present,
        "seed_routes_total": len(SEED_ROUTES),
    }


async def seed_database(session: AsyncSession, *, mode: str = "insert") -> SeedReport:
    """Apply the deterministic demo dataset (`data.seed_dataset`) to the
    database.

    mode="insert" (default): create only rows that are currently absent
    (checked by deterministic ID). A row that already exists is left
    completely untouched, even if its fields no longer match the current
    dataset definition. This makes the operation safely repeatable: a
    second call is always a no-op against an already-seeded database.

    mode="replace": delete every row this dataset owns first (see
    `clear_seed_data`), then insert all of it fresh. Use this after
    editing `data/seed_dataset.py`, so the database picks up field
    changes (a renamed stop, a moved coordinate, a reordered route) that
    "insert" mode would otherwise silently skip. Still scoped to only
    this dataset's own deterministic IDs - never touches unrelated rows.

    Both modes insert Agencies and Stops before Routes/RouteStops (and
    flush in between), and are safe to call against a completely empty
    database or one that already has other, unrelated data in the same
    tables (e.g. from `seeding.importer`).
    """
    if mode not in VALID_SEED_MODES:
        raise ValueError(
            f"Unknown seed mode: {mode!r} (expected one of {VALID_SEED_MODES})"
        )

    if mode == "replace":
        await clear_seed_data(session)

    report = SeedReport(mode=mode)

    agency_key_to_id: dict[str, uuid.UUID] = {}
    for agency in SEED_AGENCIES:
        aid = agency_id(agency.key)
        agency_key_to_id[agency.key] = aid
        if await session.get(Agency, aid) is not None:
            report.agencies_skipped += 1
            continue
        session.add(
            Agency(id=aid, name=agency.name, network_type=agency.network_type)
        )
        report.agencies_created += 1

    stop_key_to_id: dict[str, uuid.UUID] = {}
    for stop in SEED_STOPS:
        sid = stop_id(stop.key)
        stop_key_to_id[stop.key] = sid
        if await session.get(Stop, sid) is not None:
            report.stops_skipped += 1
            continue
        session.add(
            Stop(
                id=sid,
                name=stop.name,
                location=f"SRID=4326;POINT({stop.longitude} {stop.latitude})",
            )
        )
        report.stops_created += 1

    # Flush so the FK columns set below (agency_id/stop_id on the rows
    # created above) are actually satisfiable, regardless of whether this
    # AsyncSession is dedicated to this call or shared with other work.
    await session.flush()

    for route in SEED_ROUTES:
        rid = route_id(route.key)
        if await session.get(Route, rid) is None:
            session.add(
                Route(
                    id=rid,
                    agency_id=agency_key_to_id[route.agency_key],
                    short_name=route.short_name,
                    long_name=route.long_name,
                    color=route.color,
                )
            )
            report.routes_created += 1
        else:
            report.routes_skipped += 1

        for sequence, stop_key in enumerate(route.stop_keys, start=1):
            rsid = route_stop_id(route.key, sequence)
            if await session.get(RouteStop, rsid) is not None:
                report.route_stops_skipped += 1
                continue
            session.add(
                RouteStop(
                    id=rsid,
                    route_id=rid,
                    stop_id=stop_key_to_id[stop_key],
                    sequence=sequence,
                )
            )
            report.route_stops_created += 1

    await session.commit()
    return report
