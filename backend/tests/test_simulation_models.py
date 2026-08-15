"""
Tests for the realtime/simulation models (Vehicle, Trip, StopTime,
VehiclePosition) and their Alembic migration.

Follows the same three-tier structure as `tests/test_transit_models.py`:

1. Metadata-only tests - no database required.
2. Live-database model tests - real PostgreSQL/PostGIS via `DATABASE_URL`,
   each wrapped in a rolled-back transaction. Skipped if unreachable.
3. A live migration test - upgrades/downgrades a throwaway database
   created and dropped just for the test, targeting this workstream's own
   migration revision specifically (not "head") so it stays correct
   regardless of what other, independently-migrating workstreams add
   later - see this workstream's migration file for why.
"""

import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import settings  # noqa: E402
from db.base import Base  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop, StopTime, Trip, Vehicle  # noqa: E402
from db.models import VehiclePosition  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THIS_REVISION = "136e034f7a89"

# ---------------------------------------------------------------------------
# Tier 1: metadata-only tests (no database required)
# ---------------------------------------------------------------------------


def test_simulation_models_import_successfully():
    assert Vehicle.__tablename__ == "vehicles"
    assert Trip.__tablename__ == "trips"
    assert StopTime.__tablename__ == "stop_times"
    assert VehiclePosition.__tablename__ == "vehicle_positions"


def test_metadata_registers_the_four_new_tables():
    assert {"vehicles", "trips", "stop_times", "vehicle_positions"} <= set(
        Base.metadata.tables
    )


def test_vehicle_fleet_number_is_unique():
    vehicles = Base.metadata.tables["vehicles"]
    unique_constraints = [
        c for c in vehicles.constraints if isinstance(c, sa.UniqueConstraint)
    ]
    assert any(
        {col.name for col in uc.columns} == {"fleet_number"}
        for uc in unique_constraints
    )


def test_trip_foreign_keys_and_status_constraint():
    trips = Base.metadata.tables["trips"]

    route_fks = list(trips.c.route_id.foreign_keys)
    vehicle_fks = list(trips.c.vehicle_id.foreign_keys)
    assert route_fks[0].column.table.name == "routes"
    assert route_fks[0].constraint.ondelete == "CASCADE"
    assert not trips.c.route_id.nullable

    assert vehicle_fks[0].column.table.name == "vehicles"
    assert vehicle_fks[0].constraint.ondelete == "SET NULL"
    assert trips.c.vehicle_id.nullable

    check_constraints = [
        c for c in trips.constraints if isinstance(c, sa.CheckConstraint)
    ]
    assert any("scheduled" in str(c.sqltext) for c in check_constraints)


def test_stop_time_foreign_keys_sequence_and_uniqueness():
    stop_times = Base.metadata.tables["stop_times"]

    trip_fks = list(stop_times.c.trip_id.foreign_keys)
    stop_fks = list(stop_times.c.stop_id.foreign_keys)
    assert trip_fks[0].column.table.name == "trips"
    assert trip_fks[0].constraint.ondelete == "CASCADE"
    assert stop_fks[0].column.table.name == "stops"
    assert stop_fks[0].constraint.ondelete == "CASCADE"

    assert not stop_times.c.sequence.nullable

    unique_constraints = [
        c for c in stop_times.constraints if isinstance(c, sa.UniqueConstraint)
    ]
    assert any(
        {col.name for col in uc.columns} == {"trip_id", "sequence"}
        for uc in unique_constraints
    ), "expected a UNIQUE(trip_id, sequence) constraint on stop_times"


def test_vehicle_position_foreign_keys_and_status_constraint():
    positions = Base.metadata.tables["vehicle_positions"]

    vehicle_fks = list(positions.c.vehicle_id.foreign_keys)
    trip_fks = list(positions.c.trip_id.foreign_keys)
    assert vehicle_fks[0].column.table.name == "vehicles"
    assert vehicle_fks[0].constraint.ondelete == "CASCADE"
    assert not positions.c.vehicle_id.nullable

    assert trip_fks[0].column.table.name == "trips"
    assert trip_fks[0].constraint.ondelete == "SET NULL"
    assert positions.c.trip_id.nullable

    check_constraints = [
        c for c in positions.constraints if isinstance(c, sa.CheckConstraint)
    ]
    assert any("en_route" in str(c.sqltext) for c in check_constraints)


def test_vehicle_position_has_vehicle_id_recorded_at_index():
    positions = Base.metadata.tables["vehicle_positions"]
    index_names = {index.name for index in positions.indexes}
    assert "ix_vehicle_positions_vehicle_id_recorded_at" in index_names


def test_simulation_timestamps_are_timezone_aware():
    for table_name in ("vehicles", "trips", "stop_times", "vehicle_positions"):
        table = Base.metadata.tables[table_name]
        for col_name in ("created_at", "updated_at"):
            col = table.c[col_name]
            assert isinstance(col.type, sa.DateTime)
            assert col.type.timezone is True
            assert not col.nullable

    trips = Base.metadata.tables["trips"]
    assert trips.c.scheduled_start_time.type.timezone is True

    positions = Base.metadata.tables["vehicle_positions"]
    assert positions.c.recorded_at.type.timezone is True


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


@pytest_asyncio.fixture
async def db_session():
    """Same SAVEPOINT-rollback pattern as tests/test_transit_models.py."""
    if not await _database_reachable(settings.DATABASE_URL):
        pytest.skip(
            f"DATABASE_URL ({settings.DATABASE_URL}) is not reachable - "
            "skipping tests that need the real PostgreSQL/PostGIS database"
        )

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


@pytest_asyncio.fixture
async def seeded_route(db_session):
    """One agency, one route, two stops - the minimum needed to attach a
    Trip/StopTime/Vehicle/VehiclePosition to."""
    agency = Agency(name=f"Test Agency {uuid.uuid4()}", network_type="brt")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="T-1", long_name="Test Route")
    db_session.add(route)
    await db_session.flush()

    stop_a = Stop(name="Stop A", location="SRID=4326;POINT(73.0479 33.6844)")
    stop_b = Stop(name="Stop B", location="SRID=4326;POINT(73.0551 33.6938)")
    db_session.add_all([stop_a, stop_b])
    await db_session.flush()

    db_session.add_all(
        [
            RouteStop(route_id=route.id, stop_id=stop_a.id, sequence=1),
            RouteStop(route_id=route.id, stop_id=stop_b.id, sequence=2),
        ]
    )
    await db_session.flush()

    return {"route": route, "stops": [stop_a, stop_b]}


@pytest.mark.asyncio
async def test_can_insert_and_query_vehicle_trip_stop_time(db_session, seeded_route):
    route = seeded_route["route"]
    stop_a, stop_b = seeded_route["stops"]

    vehicle = Vehicle(fleet_number=f"BUS-{uuid.uuid4().hex[:6]}")
    db_session.add(vehicle)
    await db_session.flush()

    trip = Trip(
        route_id=route.id,
        vehicle_id=vehicle.id,
        status="active",
        scheduled_start_time=datetime.now(timezone.utc),
    )
    db_session.add(trip)
    await db_session.flush()

    db_session.add_all(
        [
            StopTime(
                trip_id=trip.id,
                stop_id=stop_a.id,
                sequence=1,
                arrival_offset_s=0,
                departure_offset_s=20,
            ),
            StopTime(
                trip_id=trip.id,
                stop_id=stop_b.id,
                sequence=2,
                arrival_offset_s=200,
                departure_offset_s=200,
            ),
        ]
    )
    await db_session.flush()

    result = await db_session.execute(
        sa.select(StopTime)
        .where(StopTime.trip_id == trip.id)
        .order_by(StopTime.sequence)
    )
    stop_times = result.scalars().all()
    assert [st.sequence for st in stop_times] == [1, 2]
    assert stop_times[0].stop_id == stop_a.id


@pytest.mark.asyncio
async def test_stop_time_sequence_uniqueness_is_enforced(db_session, seeded_route):
    route = seeded_route["route"]
    stop_a, stop_b = seeded_route["stops"]

    trip = Trip(
        route_id=route.id,
        status="scheduled",
        scheduled_start_time=datetime.now(timezone.utc),
    )
    db_session.add(trip)
    await db_session.flush()

    db_session.add(
        StopTime(
            trip_id=trip.id,
            stop_id=stop_a.id,
            sequence=1,
            arrival_offset_s=0,
            departure_offset_s=0,
        )
    )
    await db_session.flush()

    db_session.add(
        StopTime(
            trip_id=trip.id,
            stop_id=stop_b.id,
            sequence=1,  # duplicate sequence for the same trip
            arrival_offset_s=100,
            departure_offset_s=100,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_stop_time_departure_before_arrival_is_rejected(
    db_session, seeded_route
):
    route = seeded_route["route"]
    stop_a = seeded_route["stops"][0]

    trip = Trip(
        route_id=route.id,
        status="scheduled",
        scheduled_start_time=datetime.now(timezone.utc),
    )
    db_session.add(trip)
    await db_session.flush()

    db_session.add(
        StopTime(
            trip_id=trip.id,
            stop_id=stop_a.id,
            sequence=1,
            arrival_offset_s=100,
            departure_offset_s=50,  # before arrival - invalid
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_trip_status_check_constraint_rejects_invalid_status(
    db_session, seeded_route
):
    route = seeded_route["route"]
    db_session.add(
        Trip(
            route_id=route.id,
            status="not-a-real-status",
            scheduled_start_time=datetime.now(timezone.utc),
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_deleting_vehicle_sets_trip_vehicle_id_to_null_not_cascade(
    db_session, seeded_route
):
    """Removing a Vehicle must not delete its Trip history - vehicle_id
    is ON DELETE SET NULL, not CASCADE."""
    route = seeded_route["route"]
    vehicle = Vehicle(fleet_number=f"BUS-{uuid.uuid4().hex[:6]}")
    db_session.add(vehicle)
    await db_session.flush()

    trip = Trip(
        route_id=route.id,
        vehicle_id=vehicle.id,
        status="active",
        scheduled_start_time=datetime.now(timezone.utc),
    )
    db_session.add(trip)
    await db_session.flush()
    trip_id = trip.id

    await db_session.delete(vehicle)
    await db_session.flush()
    db_session.expire_all()

    reloaded = await db_session.get(Trip, trip_id)
    assert reloaded is not None
    assert reloaded.vehicle_id is None


@pytest.mark.asyncio
async def test_deleting_trip_cascades_to_its_stop_times(db_session, seeded_route):
    route = seeded_route["route"]
    stop_a = seeded_route["stops"][0]

    trip = Trip(
        route_id=route.id,
        status="scheduled",
        scheduled_start_time=datetime.now(timezone.utc),
    )
    db_session.add(trip)
    await db_session.flush()

    stop_time = StopTime(
        trip_id=trip.id,
        stop_id=stop_a.id,
        sequence=1,
        arrival_offset_s=0,
        departure_offset_s=0,
    )
    db_session.add(stop_time)
    await db_session.flush()
    stop_time_id = stop_time.id

    await db_session.delete(trip)
    await db_session.flush()

    remaining = await db_session.get(StopTime, stop_time_id)
    assert remaining is None


@pytest.mark.asyncio
async def test_vehicle_position_round_trip_and_latitude_bounds(
    db_session, seeded_route
):
    route = seeded_route["route"]
    stop_a, stop_b = seeded_route["stops"]

    vehicle = Vehicle(fleet_number=f"BUS-{uuid.uuid4().hex[:6]}")
    db_session.add(vehicle)
    await db_session.flush()

    trip = Trip(
        route_id=route.id,
        vehicle_id=vehicle.id,
        status="active",
        scheduled_start_time=datetime.now(timezone.utc) - timedelta(seconds=50),
    )
    db_session.add(trip)
    await db_session.flush()

    position = VehiclePosition(
        vehicle_id=vehicle.id,
        trip_id=trip.id,
        latitude=33.69,
        longitude=73.05,
        recorded_at=datetime.now(timezone.utc),
        current_stop_id=stop_a.id,
        next_stop_id=stop_b.id,
        status="en_route",
    )
    db_session.add(position)
    await db_session.flush()

    reloaded = await db_session.get(VehiclePosition, position.id)
    assert reloaded.status == "en_route"
    assert reloaded.latitude == pytest.approx(33.69)

    # Out-of-range latitude must be rejected by the DB-level CHECK.
    db_session.add(
        VehiclePosition(
            vehicle_id=vehicle.id,
            trip_id=trip.id,
            latitude=999.0,
            longitude=73.05,
            recorded_at=datetime.now(timezone.utc),
            status="en_route",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_deleting_vehicle_cascades_to_its_positions(db_session, seeded_route):
    route = seeded_route["route"]
    vehicle = Vehicle(fleet_number=f"BUS-{uuid.uuid4().hex[:6]}")
    db_session.add(vehicle)
    await db_session.flush()

    trip = Trip(
        route_id=route.id,
        vehicle_id=vehicle.id,
        status="active",
        scheduled_start_time=datetime.now(timezone.utc),
    )
    db_session.add(trip)
    await db_session.flush()

    position = VehiclePosition(
        vehicle_id=vehicle.id,
        trip_id=trip.id,
        latitude=0.0,
        longitude=0.0,
        recorded_at=datetime.now(timezone.utc),
        status="at_stop",
    )
    db_session.add(position)
    await db_session.flush()
    position_id = position.id

    await db_session.delete(vehicle)
    await db_session.flush()

    remaining = await db_session.get(VehiclePosition, position_id)
    assert remaining is None


# ---------------------------------------------------------------------------
# Tier 3: a live migration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulation_migration_applies_to_a_fresh_postgis_database():
    """Runs `alembic upgrade <this revision>` / `downgrade -1` against a
    brand-new throwaway database (built on top of the foundational
    migration), verifying this workstream's migration in isolation from
    whatever other, independently-migrating workstreams may add later -
    upgrading to "head" here would be unstable if another workstream's
    migration lands with a different, incompatible revision graph.
    """
    admin_url = settings.DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
    test_db_name = f"karwan_e_khizr_test_sim_migration_{uuid.uuid4().hex[:8]}"

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
            [sys.executable, "-m", "alembic", "upgrade", THIS_REVISION],
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
        assert set(tables) >= {
            "vehicles",
            "trips",
            "stop_times",
            "vehicle_positions",
            # Confirms this migration builds on top of the foundational one.
            "agencies",
            "routes",
            "stops",
            "route_stops",
        }

        downgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "-1"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        assert downgrade.returncode == 0, downgrade.stdout + downgrade.stderr

        verify_engine = create_async_engine(test_db_url)
        async with verify_engine.connect() as conn:
            tables_after_downgrade = (
                await conn.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            ).scalars().all()
        await verify_engine.dispose()
        assert "vehicles" not in tables_after_downgrade
        assert "trips" not in tables_after_downgrade
        # The foundational tables must survive this workstream's downgrade.
        assert "agencies" in tables_after_downgrade
    finally:
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
