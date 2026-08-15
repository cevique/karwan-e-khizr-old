"""
Tests for the isolated dev/demo simulation control API
(`api/transit/realtime/control_router.py`).

Same "own small FastAPI test app" approach as `tests/test_realtime_api.py`
- this router is deliberately never mounted on the real `main.app` by
this workstream (see that module's own docstring on why).
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from api.transit.realtime.control_router import router as control_router
from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop, Vehicle  # noqa: E402
from db.session import get_session  # noqa: E402


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


@pytest_asyncio.fixture
async def client(db_session):
    app = FastAPI()
    app.include_router(control_router, prefix="/api")

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


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
# POST /api/transit/realtime/simulation/routes/{route_id}/demo-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_demo_trip_creates_scheduled_trip(client, seeded_route):
    response = await client.post(
        f"/api/transit/realtime/simulation/routes/{seeded_route.id}/demo-trip",
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route_id"] == str(seeded_route.id)
    assert body["status"] == "scheduled"
    assert body["vehicle_id"] is None


@pytest.mark.asyncio
async def test_create_demo_trip_with_vehicle_starts_immediately(
    client, seeded_route, vehicle
):
    response = await client.post(
        f"/api/transit/realtime/simulation/routes/{seeded_route.id}/demo-trip",
        json={"vehicle_id": str(vehicle.id)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"
    assert body["vehicle_id"] == str(vehicle.id)


@pytest.mark.asyncio
async def test_create_demo_trip_422_for_route_with_no_stops(client, db_session):
    agency = Agency(name=f"Empty Agency {uuid.uuid4()}", network_type="brt")
    db_session.add(agency)
    await db_session.flush()
    empty_route = Route(
        agency_id=agency.id, short_name="EMPTY", long_name="No Stops"
    )
    db_session.add(empty_route)
    await db_session.flush()

    response = await client.post(
        f"/api/transit/realtime/simulation/routes/{empty_route.id}/demo-trip",
        json={},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/transit/realtime/simulation/trips/{trip_id}/start & /stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_and_stop_trip_round_trip(client, seeded_route, vehicle):
    demo_response = await client.post(
        f"/api/transit/realtime/simulation/routes/{seeded_route.id}/demo-trip",
        json={},
    )
    trip_id = demo_response.json()["id"]

    start_response = await client.post(
        f"/api/transit/realtime/simulation/trips/{trip_id}/start",
        json={"vehicle_id": str(vehicle.id)},
    )
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "active"

    stop_response = await client.post(
        f"/api/transit/realtime/simulation/trips/{trip_id}/stop"
    )
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_start_trip_404_for_nonexistent_trip(client, vehicle):
    response = await client.post(
        f"/api/transit/realtime/simulation/trips/{uuid.uuid4()}/start",
        json={"vehicle_id": str(vehicle.id)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_start_trip_404_for_nonexistent_vehicle(client, seeded_route):
    demo_response = await client.post(
        f"/api/transit/realtime/simulation/routes/{seeded_route.id}/demo-trip",
        json={},
    )
    trip_id = demo_response.json()["id"]

    response = await client.post(
        f"/api/transit/realtime/simulation/trips/{trip_id}/start",
        json={"vehicle_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stop_trip_404_for_nonexistent_trip(client):
    response = await client.post(
        f"/api/transit/realtime/simulation/trips/{uuid.uuid4()}/stop"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/transit/realtime/simulation/vehicles/{vehicle_id}/record-position
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_position_for_active_vehicle(client, seeded_route, vehicle):
    demo_response = await client.post(
        f"/api/transit/realtime/simulation/routes/{seeded_route.id}/demo-trip",
        json={"vehicle_id": str(vehicle.id)},
    )
    assert demo_response.json()["status"] == "active"

    response = await client.post(
        f"/api/transit/realtime/simulation/vehicles/{vehicle.id}/record-position"
    )
    assert response.status_code == 200
    assert "id" in response.json()
    assert "recorded_at" in response.json()


@pytest.mark.asyncio
async def test_record_position_404_for_vehicle_with_no_active_trip(client, vehicle):
    response = await client.post(
        f"/api/transit/realtime/simulation/vehicles/{vehicle.id}/record-position"
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/transit/realtime/simulation/state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simulation_state_empty_initially(client):
    response = await client.get("/api/transit/realtime/simulation/state")
    assert response.status_code == 200
    assert response.json() == {"active_trip_ids": []}


@pytest.mark.asyncio
async def test_simulation_state_reflects_active_trip(client, seeded_route, vehicle):
    demo_response = await client.post(
        f"/api/transit/realtime/simulation/routes/{seeded_route.id}/demo-trip",
        json={"vehicle_id": str(vehicle.id)},
    )
    trip_id = demo_response.json()["id"]

    response = await client.get("/api/transit/realtime/simulation/state")
    assert response.status_code == 200
    assert trip_id in response.json()["active_trip_ids"]
