"""
Tests for `seeding.seed` (apply/reset/status of the deterministic demo
dataset) against the real PostgreSQL/PostGIS database.

Follows the same tiering/skip convention as `tests/test_transit_models.py`:
metadata/pure-Python checks always run; anything touching the real
database uses the `db_session` fixture below (a rolled-back-on-teardown
SAVEPOINT session, copied from that file's own fixture - see its
docstring for why every test file in this project defines its own copy
rather than sharing one via a conftest) and is skipped, not failed, if
`DATABASE_URL` isn't reachable.
"""

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from core.config import settings  # noqa: E402
from data.seed_dataset import (  # noqa: E402
    SEED_AGENCIES,
    SEED_ROUTES,
    SEED_STOPS,
    agency_id,
    route_id,
    stop_id,
)
from db.models import Agency, Route, RouteStop, Stop  # noqa: E402
from seeding.seed import (  # noqa: E402
    clear_seed_data,
    get_seed_status,
    seed_database,
    seed_dataset_as_import_dataset,
)
from seeding.validation import validate_dataset  # noqa: E402


# ---------------------------------------------------------------------------
# Pure, no-database tests
# ---------------------------------------------------------------------------


def test_deterministic_ids_are_stable_across_calls():
    """The whole "deterministic dataset" requirement rests on this: the
    same key always derives the same UUID, on this or any machine/run."""
    assert agency_id("islamabad_metrobus") == agency_id("islamabad_metrobus")
    assert stop_id("faizabad") == stop_id("faizabad")
    assert agency_id("islamabad_metrobus") != agency_id("rawalpindi_metrobus")
    assert stop_id("faizabad") != stop_id("saddar")


def test_seed_dataset_has_no_duplicate_keys():
    assert len({a.key for a in SEED_AGENCIES}) == len(SEED_AGENCIES)
    assert len({s.key for s in SEED_STOPS}) == len(SEED_STOPS)
    assert len({r.key for r in SEED_ROUTES}) == len(SEED_ROUTES)


def test_seed_dataset_routes_reference_known_agencies_and_stops():
    agency_keys = {a.key for a in SEED_AGENCIES}
    stop_keys = {s.key for s in SEED_STOPS}
    for route in SEED_ROUTES:
        assert route.agency_key in agency_keys
        for stop_key in route.stop_keys:
            assert stop_key in stop_keys


def test_seed_dataset_demonstrates_multiple_routes_and_transfers():
    """Sanity-checks the demo dataset's own shape against what the task
    asked it to demonstrate: multiple routes, and at least one shared
    stop (a same-stop transfer) between two different routes."""
    assert len(SEED_ROUTES) >= 2

    stop_key_to_routes: dict[str, set[str]] = {}
    for route in SEED_ROUTES:
        for stop_key in route.stop_keys:
            stop_key_to_routes.setdefault(stop_key, set()).add(route.key)

    shared_stops = {k: v for k, v in stop_key_to_routes.items() if len(v) > 1}
    assert shared_stops, "expected at least one stop shared by two seed routes"


def test_seed_dataset_passes_its_own_validation():
    result = validate_dataset(seed_dataset_as_import_dataset())
    assert result.is_valid, [(*e.__dict__.values(),) for e in result.errors]


# ---------------------------------------------------------------------------
# Live-database tests
# ---------------------------------------------------------------------------


async def _database_reachable(url: str) -> bool:
    try:
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def db_session():
    """A real AsyncSession bound to the application's own DATABASE_URL,
    nested inside an outer transaction that is always rolled back on
    teardown (SAVEPOINT pattern), so nothing this file does ever persists
    in the developer's database - copied from
    `tests/test_transit_models.py`'s fixture of the same name."""
    if not await _database_reachable(settings.DATABASE_URL):
        pytest.skip(
            f"DATABASE_URL ({settings.DATABASE_URL}) is not reachable - "
            "skipping tests that need the real PostgreSQL/PostGIS database"
        )

    from sqlalchemy.ext.asyncio import AsyncSession

    engine = create_async_engine(settings.DATABASE_URL)
    connection = await engine.connect()
    outer_transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    await connection.begin_nested()

    @sa.event.listens_for(session.sync_session, "after_transaction_end")
    def _restart_savepoint(sync_session, transaction):
        if transaction.nested and not transaction._parent.nested:
            sync_session.begin_nested()

    try:
        yield session
    finally:
        await session.close()
        await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_seed_database_on_empty_database(db_session):
    """`seed_database` must work starting from a totally empty database -
    this rolled-back-transaction session genuinely is one, since no seed
    row can exist here unless another test in the same run put it there
    (none do - see this file's and test_admin_router.py's cleanup)."""
    report = await seed_database(db_session, mode="insert")

    assert report.agencies_created == len(SEED_AGENCIES)
    assert report.stops_created == len(SEED_STOPS)
    assert report.routes_created == len(SEED_ROUTES)
    assert report.agencies_skipped == 0
    assert report.stops_skipped == 0


@pytest.mark.asyncio
async def test_seed_database_is_deterministic(db_session):
    """Seeding twice in a row (against two logically-empty starting
    points, since neither commits past this test) produces the exact
    same row IDs both times."""
    await seed_database(db_session, mode="insert")
    first_agency = await db_session.get(Agency, agency_id("islamabad_metrobus"))
    first_stop = await db_session.get(Stop, stop_id("faizabad"))

    await clear_seed_data(db_session)
    await seed_database(db_session, mode="insert")
    second_agency = await db_session.get(Agency, agency_id("islamabad_metrobus"))
    second_stop = await db_session.get(Stop, stop_id("faizabad"))

    assert first_agency.id == second_agency.id == agency_id("islamabad_metrobus")
    assert first_stop.id == second_stop.id == stop_id("faizabad")


@pytest.mark.asyncio
async def test_seed_database_insert_mode_is_repeatable(db_session):
    """Calling seed twice with mode="insert" is a safe no-op the second
    time: nothing created, everything reported as skipped."""
    first = await seed_database(db_session, mode="insert")
    assert first.agencies_created == len(SEED_AGENCIES)

    second = await seed_database(db_session, mode="insert")
    assert second.agencies_created == 0
    assert second.stops_created == 0
    assert second.routes_created == 0
    assert second.route_stops_created == 0
    assert second.agencies_skipped == len(SEED_AGENCIES)
    assert second.stops_skipped == len(SEED_STOPS)


@pytest.mark.asyncio
async def test_seed_database_insert_mode_leaves_modified_rows_untouched(db_session):
    """mode="insert" never overwrites an existing row's fields, even if
    they no longer match the current dataset definition."""
    await seed_database(db_session, mode="insert")

    faizabad = await db_session.get(Stop, stop_id("faizabad"))
    faizabad.name = "Manually Renamed Stop"
    await db_session.flush()

    await seed_database(db_session, mode="insert")

    reloaded = await db_session.get(Stop, stop_id("faizabad"))
    assert reloaded.name == "Manually Renamed Stop"


@pytest.mark.asyncio
async def test_seed_database_replace_mode_restores_dataset_definition(db_session):
    """mode="replace" deletes and re-creates the seed rows, so it DOES
    pick up a definition change that mode="insert" would ignore."""
    await seed_database(db_session, mode="insert")

    faizabad = await db_session.get(Stop, stop_id("faizabad"))
    faizabad.name = "Manually Renamed Stop"
    await db_session.flush()

    await seed_database(db_session, mode="replace")

    reloaded = await db_session.get(Stop, stop_id("faizabad"))
    assert reloaded.name == "Faizabad"


@pytest.mark.asyncio
async def test_seed_database_relationships_are_ordered_by_sequence(db_session):
    """Round-trips a route's stops through the real RouteStop
    relationship (ordered by sequence, per db/models/route.py), matching
    the seed dataset's own declared stop order exactly."""
    from sqlalchemy.orm import selectinload

    await seed_database(db_session, mode="insert")

    blue_line_route = SEED_ROUTES[0]
    assert blue_line_route.key == "blue_line"

    result = await db_session.execute(
        sa.select(Route)
        .options(selectinload(Route.route_stops).selectinload(RouteStop.stop))
        .where(Route.id == route_id("blue_line"))
    )
    route = result.scalar_one()

    ordered_stop_names = [rs.stop.name for rs in route.route_stops]
    expected_names = [
        s.name for key in blue_line_route.stop_keys
        for s in SEED_STOPS if s.key == key
    ]
    assert ordered_stop_names == expected_names


@pytest.mark.asyncio
async def test_seed_database_stop_coordinates_round_trip_through_postgis(db_session):
    await seed_database(db_session, mode="insert")

    lon, lat = (
        await db_session.execute(
            sa.text(
                "SELECT ST_X(location::geometry), ST_Y(location::geometry) "
                "FROM stops WHERE id = :id"
            ),
            {"id": stop_id("faizabad")},
        )
    ).one()
    faizabad = next(s for s in SEED_STOPS if s.key == "faizabad")
    assert lon == pytest.approx(faizabad.longitude, abs=1e-4)
    assert lat == pytest.approx(faizabad.latitude, abs=1e-4)


@pytest.mark.asyncio
async def test_clear_seed_data_removes_only_seed_rows(db_session):
    """Reset must not touch unrelated data that happens to live in the
    same tables - proven here by seeding a genuinely unrelated Agency
    (a random, non-deterministic ID) alongside the seed dataset, then
    confirming reset leaves it completely alone."""
    await seed_database(db_session, mode="insert")

    unrelated = Agency(name=f"Unrelated Agency {uuid.uuid4()}", network_type="other")
    db_session.add(unrelated)
    await db_session.flush()
    unrelated_id = unrelated.id

    await clear_seed_data(db_session)

    assert await db_session.get(Agency, agency_id("islamabad_metrobus")) is None
    assert await db_session.get(Stop, stop_id("faizabad")) is None
    assert await db_session.get(Agency, unrelated_id) is not None


@pytest.mark.asyncio
async def test_get_seed_status_reflects_presence(db_session):
    status_before = await get_seed_status(db_session)
    assert status_before["seed_agencies_present"] == 0

    await seed_database(db_session, mode="insert")

    status_after = await get_seed_status(db_session)
    assert status_after["seed_agencies_present"] == len(SEED_AGENCIES)
    assert status_after["seed_agencies_total"] == len(SEED_AGENCIES)
    assert status_after["seed_stops_present"] == len(SEED_STOPS)
    assert status_after["seed_routes_present"] == len(SEED_ROUTES)


@pytest.mark.asyncio
async def test_seed_database_rejects_unknown_mode(db_session):
    with pytest.raises(ValueError):
        await seed_database(db_session, mode="not-a-real-mode")
