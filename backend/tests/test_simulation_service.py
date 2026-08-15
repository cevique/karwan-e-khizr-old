"""
Tests for `simulation.service.SimulationService` (start/stop a trip,
record a position snapshot, inspect state) and
`simulation.trip_builder.build_trip_for_route`.

Same rolled-back-transaction `db_session` fixture pattern as the other
simulation test modules.
"""

from __future__ import annotations

import os
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
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop, Vehicle, VehiclePosition  # noqa: E402
from simulation.service import (  # noqa: E402
    SimulationService,
    TripNotFoundError,
    VehicleNotFoundError,
)
from simulation.trip_builder import build_trip_for_route  # noqa: E402


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
    agency = Agency(name=f"Test Agency {uuid.uuid4()}", network_type="brt")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="T-1", long_name="Test Route")
    db_session.add(route)
    await db_session.flush()

    stop_a = Stop(name="Stop A", location="SRID=4326;POINT(73.0000 33.0000)")
    stop_b = Stop(name="Stop B", location="SRID=4326;POINT(73.1000 33.0000)")
    db_session.add_all([stop_a, stop_b])
    await db_session.flush()

    db_session.add_all(
        [
            RouteStop(route_id=route.id, stop_id=stop_a.id, sequence=1),
            RouteStop(route_id=route.id, stop_id=stop_b.id, sequence=2),
        ]
    )
    await db_session.flush()

    return route


@pytest_asyncio.fixture
async def vehicle(db_session):
    v = Vehicle(fleet_number=f"BUS-{uuid.uuid4().hex[:6]}")
    db_session.add(v)
    await db_session.flush()
    return v


# ---------------------------------------------------------------------------
# simulation.trip_builder.build_trip_for_route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_trip_for_route_creates_trip_and_ordered_stop_times(
    db_session, seeded_route
):
    trip = await build_trip_for_route(db_session, seeded_route.id)
    assert trip.route_id == seeded_route.id
    assert trip.status == "scheduled"

    result = await db_session.execute(
        sa.text(
            "SELECT sequence FROM stop_times "
            "WHERE trip_id = :trip_id ORDER BY sequence"
        ),
        {"trip_id": trip.id},
    )
    sequences = [row[0] for row in result.all()]
    assert sequences == [1, 2]


@pytest.mark.asyncio
async def test_build_trip_for_route_raises_for_route_with_no_stops(db_session):
    agency = Agency(name=f"Empty Agency {uuid.uuid4()}", network_type="brt")
    db_session.add(agency)
    await db_session.flush()
    empty_route = Route(
        agency_id=agency.id, short_name="EMPTY", long_name="No Stops Route"
    )
    db_session.add(empty_route)
    await db_session.flush()

    with pytest.raises(ValueError):
        await build_trip_for_route(db_session, empty_route.id)


@pytest.mark.asyncio
async def test_build_trip_for_route_raises_for_nonexistent_route(db_session):
    with pytest.raises(ValueError):
        await build_trip_for_route(db_session, uuid.uuid4())


# ---------------------------------------------------------------------------
# SimulationService.start_trip / stop_trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_trip_assigns_vehicle_and_marks_active(
    db_session, seeded_route, vehicle
):
    trip = await build_trip_for_route(db_session, seeded_route.id)
    service = SimulationService()

    start_time = datetime.now(timezone.utc)
    updated = await service.start_trip(
        db_session, trip_id=trip.id, vehicle_id=vehicle.id, start_time=start_time
    )
    assert updated.status == "active"
    assert updated.vehicle_id == vehicle.id
    assert updated.scheduled_start_time == start_time


@pytest.mark.asyncio
async def test_start_trip_defaults_start_time_to_now_when_omitted(
    db_session, seeded_route, vehicle
):
    trip = await build_trip_for_route(db_session, seeded_route.id)
    fixed_now = datetime.now(timezone.utc)
    service = SimulationService(clock=lambda: fixed_now)

    updated = await service.start_trip(
        db_session, trip_id=trip.id, vehicle_id=vehicle.id
    )
    assert updated.scheduled_start_time == fixed_now


@pytest.mark.asyncio
async def test_start_trip_raises_for_nonexistent_trip(db_session, vehicle):
    service = SimulationService()
    with pytest.raises(TripNotFoundError):
        await service.start_trip(
            db_session, trip_id=uuid.uuid4(), vehicle_id=vehicle.id
        )


@pytest.mark.asyncio
async def test_start_trip_raises_for_nonexistent_vehicle(db_session, seeded_route):
    trip = await build_trip_for_route(db_session, seeded_route.id)
    service = SimulationService()
    with pytest.raises(VehicleNotFoundError):
        await service.start_trip(
            db_session, trip_id=trip.id, vehicle_id=uuid.uuid4()
        )


@pytest.mark.asyncio
async def test_stop_trip_defaults_to_cancelled(db_session, seeded_route, vehicle):
    trip = await build_trip_for_route(db_session, seeded_route.id)
    service = SimulationService()
    await service.start_trip(db_session, trip_id=trip.id, vehicle_id=vehicle.id)

    stopped = await service.stop_trip(db_session, trip_id=trip.id)
    assert stopped.status == "cancelled"


@pytest.mark.asyncio
async def test_stop_trip_can_mark_completed(db_session, seeded_route, vehicle):
    trip = await build_trip_for_route(db_session, seeded_route.id)
    service = SimulationService()
    await service.start_trip(db_session, trip_id=trip.id, vehicle_id=vehicle.id)

    stopped = await service.stop_trip(db_session, trip_id=trip.id, completed=True)
    assert stopped.status == "completed"


@pytest.mark.asyncio
async def test_stop_trip_raises_for_nonexistent_trip(db_session):
    service = SimulationService()
    with pytest.raises(TripNotFoundError):
        await service.stop_trip(db_session, trip_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# SimulationService.record_position / record_all_active_positions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_position_persists_a_vehicle_position_row(
    db_session, seeded_route, vehicle
):
    trip = await build_trip_for_route(
        db_session,
        seeded_route.id,
        speed_kmh=1.0,
        scheduled_start_time=datetime.now(timezone.utc) - timedelta(seconds=10),
    )
    service = SimulationService()
    await service.start_trip(db_session, trip_id=trip.id, vehicle_id=vehicle.id)

    recorded = await service.record_position(db_session, vehicle_id=vehicle.id)
    assert recorded is not None

    reloaded = await db_session.get(VehiclePosition, recorded.id)
    assert reloaded is not None
    assert reloaded.vehicle_id == vehicle.id
    assert reloaded.trip_id == trip.id


@pytest.mark.asyncio
async def test_record_position_returns_none_for_vehicle_with_no_active_trip(
    db_session, vehicle
):
    service = SimulationService()
    assert await service.record_position(db_session, vehicle_id=vehicle.id) is None


@pytest.mark.asyncio
async def test_record_position_returns_none_for_unknown_vehicle(db_session):
    service = SimulationService()
    assert (
        await service.record_position(db_session, vehicle_id=uuid.uuid4()) is None
    )


@pytest.mark.asyncio
async def test_record_all_active_positions_covers_every_active_vehicle(
    db_session, seeded_route
):
    service = SimulationService()

    vehicle_1 = Vehicle(fleet_number=f"BUS-{uuid.uuid4().hex[:6]}")
    vehicle_2 = Vehicle(fleet_number=f"BUS-{uuid.uuid4().hex[:6]}")
    db_session.add_all([vehicle_1, vehicle_2])
    await db_session.flush()

    trip_1 = await build_trip_for_route(db_session, seeded_route.id, speed_kmh=1.0)
    trip_2 = await build_trip_for_route(db_session, seeded_route.id, speed_kmh=1.0)
    await service.start_trip(db_session, trip_id=trip_1.id, vehicle_id=vehicle_1.id)
    await service.start_trip(db_session, trip_id=trip_2.id, vehicle_id=vehicle_2.id)

    recorded = await service.record_all_active_positions(db_session)
    assert {p.vehicle_id for p in recorded} == {vehicle_1.id, vehicle_2.id}


@pytest.mark.asyncio
async def test_record_all_active_positions_is_empty_when_nothing_is_active(
    db_session,
):
    service = SimulationService()
    assert await service.record_all_active_positions(db_session) == []


# ---------------------------------------------------------------------------
# SimulationService.active_trip_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_trip_ids_reflects_only_active_trips(
    db_session, seeded_route, vehicle
):
    service = SimulationService()
    scheduled_trip = await build_trip_for_route(db_session, seeded_route.id)
    active_trip = await build_trip_for_route(db_session, seeded_route.id)
    await service.start_trip(
        db_session, trip_id=active_trip.id, vehicle_id=vehicle.id
    )

    active_ids = await service.active_trip_ids(db_session)
    assert active_trip.id in active_ids
    assert scheduled_trip.id not in active_ids


@pytest.mark.asyncio
async def test_active_trip_ids_empty_with_no_simulation_state(db_session):
    service = SimulationService()
    assert await service.active_trip_ids(db_session) == []
