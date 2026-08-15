"""
Tests for `simulation.provider`: the `VehicleLocationProvider` Protocol
substitution property, and the real `SimulatedVehicleLocationProvider`
implementation against a live database.

Uses the same rolled-back-transaction `db_session` fixture pattern as
`tests/test_simulation_models.py`, but `SimulatedVehicleLocationProvider`
needs its OWN session per call (it owns its session lifecycle - see that
class's docstring) rather than reusing the fixture's session directly, so
each test's `session_factory` is a tiny wrapper that hands back the same
rolled-back `db_session` connection every time, keeping everything inside
one outer transaction that's always rolled back.
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
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
from db.models import Agency, Route, RouteStop, Stop, Vehicle  # noqa: E402
from simulation.engine import SimulatedPosition  # noqa: E402
from simulation.provider import (  # noqa: E402
    SimulatedVehicleLocationProvider,
    VehicleLocationProvider,
)
from simulation.trip_builder import build_trip_for_route  # noqa: E402


# ---------------------------------------------------------------------------
# Protocol substitution - no database required
# ---------------------------------------------------------------------------


class _FakeVehicleLocationProvider:
    """A minimal fake satisfying `VehicleLocationProvider` structurally,
    with no database at all - demonstrates the interface really is
    substitutable, per the task's explicit "Realtime Provider" requirement
    that the exact implementation be replaceable."""

    def __init__(self, positions: dict[uuid.UUID, SimulatedPosition]):
        self._positions = positions

    async def get_vehicle_position(self, vehicle_id):
        return self._positions.get(vehicle_id)

    async def list_active_positions(self):
        return list(self._positions.values())

    async def get_positions_for_route(self, route_id):
        return [p for p in self._positions.values() if p.route_id == route_id]

    async def get_positions_for_trip(self, trip_id):
        return [p for p in self._positions.values() if p.trip_id == trip_id]


def test_fake_provider_satisfies_the_protocol_structurally():
    fake = _FakeVehicleLocationProvider({})
    assert isinstance(fake, VehicleLocationProvider)


def test_simulated_provider_satisfies_the_protocol_structurally():
    provider = SimulatedVehicleLocationProvider()
    assert isinstance(provider, VehicleLocationProvider)


@pytest.mark.asyncio
async def test_fake_provider_returns_seeded_position():
    vehicle_id, trip_id, route_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    position = SimulatedPosition(
        trip_id=trip_id,
        route_id=route_id,
        latitude=1.0,
        longitude=2.0,
        status="en_route",
        current_stop_id=None,
        next_stop_id=None,
        elapsed_s=42.0,
        vehicle_id=vehicle_id,
        as_of=now,
    )
    fake: VehicleLocationProvider = _FakeVehicleLocationProvider(
        {vehicle_id: position}
    )
    assert await fake.get_vehicle_position(vehicle_id) == position
    assert await fake.get_vehicle_position(uuid.uuid4()) is None
    assert await fake.list_active_positions() == [position]
    assert await fake.get_positions_for_route(route_id) == [position]
    assert await fake.get_positions_for_route(uuid.uuid4()) == []


# ---------------------------------------------------------------------------
# SimulatedVehicleLocationProvider against a live database
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


def _session_factory_for(db_session: AsyncSession):
    """Wrap the test's single rolled-back `db_session` as a
    `session_factory` callable, so `SimulatedVehicleLocationProvider`
    (which opens/closes its own session per call) stays inside the same
    outer transaction the test fixture will roll back."""

    @asynccontextmanager
    async def factory():
        yield db_session

    return factory


@pytest_asyncio.fixture
async def running_trip(db_session):
    """A route with two stops, a vehicle, and an active trip started 50s
    ago - positioned such that it should currently be `en_route`."""
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

    vehicle = Vehicle(fleet_number=f"BUS-{uuid.uuid4().hex[:6]}")
    db_session.add(vehicle)
    await db_session.flush()

    # A slow, generous speed so a 50s-old trip is comfortably mid-segment,
    # not already at the destination stop, regardless of exact distance.
    trip = await build_trip_for_route(
        db_session,
        route.id,
        vehicle_id=vehicle.id,
        scheduled_start_time=datetime.now(timezone.utc) - timedelta(seconds=50),
        speed_kmh=1.0,
        dwell_seconds=5.0,
    )
    trip.status = "active"
    await db_session.flush()

    return {"route": route, "vehicle": vehicle, "trip": trip}


@pytest.mark.asyncio
async def test_get_vehicle_position_returns_en_route_position(
    db_session, running_trip
):
    provider = SimulatedVehicleLocationProvider(
        session_factory=_session_factory_for(db_session)
    )
    position = await provider.get_vehicle_position(running_trip["vehicle"].id)
    assert position is not None
    assert position.status in ("en_route", "at_stop")
    assert position.vehicle_id == running_trip["vehicle"].id
    assert position.trip_id == running_trip["trip"].id


@pytest.mark.asyncio
async def test_get_vehicle_position_returns_none_for_unknown_vehicle(db_session):
    provider = SimulatedVehicleLocationProvider(
        session_factory=_session_factory_for(db_session)
    )
    assert await provider.get_vehicle_position(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_list_active_positions_is_empty_with_no_active_trips(db_session):
    provider = SimulatedVehicleLocationProvider(
        session_factory=_session_factory_for(db_session)
    )
    assert await provider.list_active_positions() == []


@pytest.mark.asyncio
async def test_list_active_positions_includes_the_running_trip(
    db_session, running_trip
):
    provider = SimulatedVehicleLocationProvider(
        session_factory=_session_factory_for(db_session)
    )
    positions = await provider.list_active_positions()
    assert len(positions) == 1
    assert positions[0].vehicle_id == running_trip["vehicle"].id


@pytest.mark.asyncio
async def test_get_positions_for_route_filters_correctly(db_session, running_trip):
    provider = SimulatedVehicleLocationProvider(
        session_factory=_session_factory_for(db_session)
    )
    matching = await provider.get_positions_for_route(running_trip["route"].id)
    assert len(matching) == 1

    non_matching = await provider.get_positions_for_route(uuid.uuid4())
    assert non_matching == []


@pytest.mark.asyncio
async def test_get_positions_for_trip_returns_single_element_list(
    db_session, running_trip
):
    provider = SimulatedVehicleLocationProvider(
        session_factory=_session_factory_for(db_session)
    )
    positions = await provider.get_positions_for_trip(running_trip["trip"].id)
    assert len(positions) == 1
    assert positions[0].trip_id == running_trip["trip"].id


@pytest.mark.asyncio
async def test_get_positions_for_trip_empty_for_nonexistent_trip(db_session):
    provider = SimulatedVehicleLocationProvider(
        session_factory=_session_factory_for(db_session)
    )
    assert await provider.get_positions_for_trip(uuid.uuid4()) == []


@pytest.mark.asyncio
async def test_provider_uses_injected_clock_deterministically(
    db_session, running_trip
):
    """Same fixed clock -> same computed position, confirming the
    provider's own determinism (not just the pure engine's) end-to-end."""
    fixed_now = datetime.now(timezone.utc)

    provider = SimulatedVehicleLocationProvider(
        session_factory=_session_factory_for(db_session), clock=lambda: fixed_now
    )
    first = await provider.get_vehicle_position(running_trip["vehicle"].id)
    second = await provider.get_vehicle_position(running_trip["vehicle"].id)
    assert first == second


@pytest.mark.asyncio
async def test_scheduled_but_not_active_trip_has_no_active_position(
    db_session, running_trip
):
    """A trip that's merely `"scheduled"` (not `"active"`) must not show
    up in `list_active_positions`/`get_vehicle_position` - only
    `get_positions_for_trip` (which looks up by trip id regardless of
    status) can see it."""
    trip = running_trip["trip"]
    trip.status = "scheduled"
    await db_session.flush()

    provider = SimulatedVehicleLocationProvider(
        session_factory=_session_factory_for(db_session)
    )
    assert await provider.get_vehicle_position(running_trip["vehicle"].id) is None
    assert await provider.list_active_positions() == []

    # But the trip-scoped lookup still finds it (schedule exists, vehicle
    # assigned) - status-agnostic by design, see get_positions_for_trip's
    # docstring.
    positions = await provider.get_positions_for_trip(trip.id)
    assert len(positions) == 1
