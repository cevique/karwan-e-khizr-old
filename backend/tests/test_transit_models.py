"""
Tests for the foundational static transit-network models (Agency, Route,
Stop, RouteStop) and their Alembic migration.

Three tiers, cheapest/most-isolated first:

1. Metadata-only tests - no database required. Verify the models import,
   register the expected tables on `Base.metadata`, and declare the
   expected columns/constraints/indexes. These always run.

2. Live-database model tests - exercise the models against the real
   PostgreSQL/PostGIS instance configured via `DATABASE_URL` (the same
   database the application itself uses), each wrapped in an outer
   transaction that is always rolled back, so nothing is ever committed
   to the developer's database. Skipped (not failed) if that database
   isn't reachable, per the instruction to avoid depending on
   infrastructure that may not be present.

3. A live migration test - runs the actual Alembic migration (upgrade
   then downgrade) against a throwaway database created and dropped
   just for the test, so it never touches the developer's existing
   `DATABASE_URL` database or any data in it. Skipped if the server
   isn't reachable or the test process can't create/drop databases.
"""

import os
import subprocess
import sys
import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import selectinload

# Settings requires DATABASE_URL/SECRET_KEY to be set; mirrors the same
# setdefault pattern used in tests/test_health.py so this file can also be
# imported/collected on its own.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

from core.config import settings  # noqa: E402
from db.base import Base  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Tier 1: metadata-only tests (no database required)
# ---------------------------------------------------------------------------


def test_models_import_successfully():
    """Sanity check: the four foundational models import and are the
    classes we expect them to be."""
    assert Agency.__tablename__ == "agencies"
    assert Route.__tablename__ == "routes"
    assert Stop.__tablename__ == "stops"
    assert RouteStop.__tablename__ == "route_stops"


def test_metadata_contains_expected_tables():
    """`db.models` registers exactly the foundational static-network
    tables on `Base.metadata` - not the later, deliberately-unbuilt ones
    (vehicles, tickets, users, ...)."""
    assert set(Base.metadata.tables) == {
        "agencies",
        "routes",
        "stops",
        "route_stops",
    }


def test_agency_route_foreign_key():
    """Route.agency_id references agencies.id with ON DELETE CASCADE."""
    routes = Base.metadata.tables["routes"]
    fks = list(routes.c.agency_id.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "agencies"
    assert fks[0].constraint.ondelete == "CASCADE"


def test_route_stop_foreign_keys():
    """RouteStop references both routes.id and stops.id, each ON DELETE
    CASCADE, and is the association *object* the design doc asked for
    (i.e. carries more than just the two foreign keys)."""
    route_stops = Base.metadata.tables["route_stops"]

    route_fks = list(route_stops.c.route_id.foreign_keys)
    stop_fks = list(route_stops.c.stop_id.foreign_keys)
    assert route_fks[0].column.table.name == "routes"
    assert route_fks[0].constraint.ondelete == "CASCADE"
    assert stop_fks[0].column.table.name == "stops"
    assert stop_fks[0].constraint.ondelete == "CASCADE"

    # Extra attributes beyond the two FKs - the reason this is an
    # association object rather than a plain many-to-many table.
    assert "sequence" in route_stops.c
    assert "distance_along_route_m" in route_stops.c


def test_route_stop_sequence_is_explicit_and_unique_per_route():
    """Ordering must come from an explicit column, not row-insertion
    order, and a route can't declare two stops at the same position."""
    route_stops = Base.metadata.tables["route_stops"]
    assert not route_stops.c.sequence.nullable

    unique_constraints = [
        c
        for c in route_stops.constraints
        if isinstance(c, sa.UniqueConstraint)
    ]
    assert any(
        {col.name for col in uc.columns} == {"route_id", "sequence"}
        for uc in unique_constraints
    ), "expected a UNIQUE(route_id, sequence) constraint on route_stops"


def test_stop_location_and_route_path_are_spatial_types():
    """Coordinates are PostGIS types, not plain lat/lon strings/floats -
    Stop.location as `geography` (used for proximity search), Route.path
    as `geometry` (used for rendering/measurement)."""
    from geoalchemy2 import Geography, Geometry

    stops = Base.metadata.tables["stops"]
    routes = Base.metadata.tables["routes"]

    assert isinstance(stops.c.location.type, Geography)
    assert stops.c.location.type.geometry_type == "POINT"
    assert stops.c.location.type.srid == 4326
    assert not stops.c.location.nullable

    assert isinstance(routes.c.path.type, Geometry)
    assert routes.c.path.type.geometry_type == "LINESTRING"
    assert routes.c.path.type.srid == 4326


def test_timestamps_are_timezone_aware():
    for table_name in ("agencies", "routes", "stops", "route_stops"):
        table = Base.metadata.tables[table_name]
        for col_name in ("created_at", "updated_at"):
            col = table.c[col_name]
            assert isinstance(col.type, sa.DateTime)
            assert col.type.timezone is True
            assert not col.nullable


# ---------------------------------------------------------------------------
# Tier 2: live-database model tests (real DATABASE_URL, rolled back always)
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


def _require_live_database():
    import asyncio

    if not asyncio.get_event_loop().run_until_complete(
        _database_reachable(settings.DATABASE_URL)
    ):
        pytest.skip(
            f"DATABASE_URL ({settings.DATABASE_URL}) is not reachable - "
            "skipping tests that need the real PostgreSQL/PostGIS database"
        )


@pytest_asyncio.fixture
async def db_session():
    """A real AsyncSession bound to the application's own DATABASE_URL,
    nested inside an outer transaction that is always rolled back on
    teardown (SAVEPOINT pattern) so nothing committed here ever persists
    in the developer's database.
    """
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

    # Start a SAVEPOINT so `session.commit()` inside a test (if any) only
    # ends the savepoint, not the outer transaction we're about to roll
    # back - a new one is opened automatically after each commit.
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
async def test_can_insert_and_query_agency_route_stop_routestop(db_session):
    """Round-trips one row through each of the four tables, using real
    PostGIS geography/geometry columns, inside a transaction that never
    commits to the developer's database."""
    agency = Agency(name=f"Test Agency {uuid.uuid4()}", network_type="brt")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="T-1", long_name="Test Route")
    db_session.add(route)

    stop_a = Stop(
        name="Test Stop A",
        location="SRID=4326;POINT(73.0479 33.6844)",  # Islamabad, roughly
    )
    stop_b = Stop(
        name="Test Stop B",
        location="SRID=4326;POINT(73.0551 33.6938)",
    )
    db_session.add_all([stop_a, stop_b])
    await db_session.flush()

    route_stop_a = RouteStop(route_id=route.id, stop_id=stop_a.id, sequence=1)
    route_stop_b = RouteStop(route_id=route.id, stop_id=stop_b.id, sequence=2)
    db_session.add_all([route_stop_a, route_stop_b])
    await db_session.flush()

    # Round-trip the geography column through PostGIS, not just Python
    # memory, to confirm it's really a spatial column server-side.
    lon, lat = (
        await db_session.execute(
            sa.text(
                "SELECT ST_X(location::geometry), ST_Y(location::geometry) "
                "FROM stops WHERE id = :id"
            ),
            {"id": stop_a.id},
        )
    ).one()
    assert lon == pytest.approx(73.0479, abs=1e-4)
    assert lat == pytest.approx(33.6844, abs=1e-4)


@pytest.mark.asyncio
async def test_route_stop_ordering_reflects_sequence_not_insertion_order(
    db_session,
):
    """Insert route_stops out of sequence order; the ordered relationship
    must come back sorted by `sequence`, not insertion order."""
    agency = Agency(name=f"Order Test Agency {uuid.uuid4()}")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="ORD-1")
    db_session.add(route)

    stop_1 = Stop(name="First", location="SRID=4326;POINT(73.00 33.60)")
    stop_2 = Stop(name="Second", location="SRID=4326;POINT(73.01 33.61)")
    stop_3 = Stop(name="Third", location="SRID=4326;POINT(73.02 33.62)")
    db_session.add_all([stop_1, stop_2, stop_3])
    await db_session.flush()

    # Insert deliberately out of order: sequence 3, then 1, then 2.
    db_session.add_all(
        [
            RouteStop(route_id=route.id, stop_id=stop_3.id, sequence=3),
            RouteStop(route_id=route.id, stop_id=stop_1.id, sequence=1),
            RouteStop(route_id=route.id, stop_id=stop_2.id, sequence=2),
        ]
    )
    await db_session.flush()

    # Re-fetch through the ORM relationship (eagerly, to stay inside the
    # async session correctly) - it must come back sorted by `sequence`
    # per Route.route_stops' `order_by`, not by insertion order.
    reloaded_route = (
        await db_session.execute(
            sa.select(Route)
            .options(selectinload(Route.route_stops))
            .where(Route.id == route.id)
        )
    ).scalar_one()

    ordered_stop_ids = [rs.stop_id for rs in reloaded_route.route_stops]
    assert ordered_stop_ids == [stop_1.id, stop_2.id, stop_3.id]


@pytest.mark.asyncio
async def test_route_stop_sequence_uniqueness_is_enforced(db_session):
    """Two RouteStops on the same route can't claim the same sequence
    position - enforced by the database, not just application code."""
    agency = Agency(name=f"Uniqueness Test Agency {uuid.uuid4()}")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="UNQ-1")
    stop_1 = Stop(name="A", location="SRID=4326;POINT(73.00 33.60)")
    stop_2 = Stop(name="B", location="SRID=4326;POINT(73.01 33.61)")
    db_session.add_all([route, stop_1, stop_2])
    await db_session.flush()

    db_session.add(RouteStop(route_id=route.id, stop_id=stop_1.id, sequence=1))
    await db_session.flush()
    db_session.add(RouteStop(route_id=route.id, stop_id=stop_2.id, sequence=1))

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_route_foreign_key_to_missing_agency_is_rejected(db_session):
    """A Route can't reference an Agency that doesn't exist."""
    db_session.add(
        Route(agency_id=uuid.uuid4(), short_name="ORPHAN-1")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_deleting_agency_cascades_to_its_routes(db_session):
    """ON DELETE CASCADE on Route.agency_id actually cascades server-side."""
    agency = Agency(name=f"Cascade Test Agency {uuid.uuid4()}")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="CASC-1")
    db_session.add(route)
    await db_session.flush()
    route_id = route.id

    await db_session.delete(agency)
    await db_session.flush()

    remaining = (
        await db_session.execute(
            sa.text("SELECT 1 FROM routes WHERE id = :id"), {"id": route_id}
        )
    ).first()
    assert remaining is None


# ---------------------------------------------------------------------------
# Tier 3: live migration test (throwaway database, never the dev database)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alembic_migration_applies_to_a_fresh_postgis_database():
    """Runs the real `alembic upgrade head` / `alembic downgrade base`
    against a brand-new database created (and always dropped again) just
    for this test - so it verifies the migration genuinely works without
    ever touching the developer's own `DATABASE_URL` database.
    """
    admin_url = settings.DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    test_db_name = f"karwan_e_khizr_test_migration_{uuid.uuid4().hex[:8]}"

    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except OperationalError:
        await admin_engine.dispose()
        pytest.skip(
            "Could not reach the PostgreSQL server via DATABASE_URL - "
            "skipping the live migration test"
        )

    try:
        async with admin_engine.connect() as conn:
            await conn.execute(sa.text(f'CREATE DATABASE "{test_db_name}"'))
    except Exception as exc:
        await admin_engine.dispose()
        pytest.skip(f"Could not create a throwaway test database: {exc}")

    test_db_url = settings.DATABASE_URL.rsplit("/", 1)[0] + f"/{test_db_name}"

    try:
        setup_engine = create_async_engine(test_db_url)
        async with setup_engine.connect() as conn:
            await conn.execute(sa.text("COMMIT"))
            await conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await setup_engine.dispose()

        env = {**os.environ, "DATABASE_URL": test_db_url}

        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr

        verify_engine = create_async_engine(test_db_url)
        async with verify_engine.connect() as conn:
            tables = (
                await conn.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            ).scalars().all()
        await verify_engine.dispose()
        assert set(tables) >= {"agencies", "routes", "stops", "route_stops"}

        downgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr
    finally:
        # Terminate any leftover connections, then always drop the
        # throwaway database - never the developer's real one.
        async with admin_engine.connect() as conn:
            await conn.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": test_db_name},
            )
            await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db_name}"'))
        await admin_engine.dispose()
