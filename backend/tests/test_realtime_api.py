"""
Tests for the public, read-only realtime vehicle-position API
(`api/transit/realtime/router.py`).

This workstream's routers are not mounted on the real `main.app` (that
would require editing `api/router.py`, out of ownership bounds - see
`api/transit/realtime/__init__.py`'s integration note). Tests here build
their own small `FastAPI` app that mounts exactly the routers this
workstream owns, at the same `/api` prefix `main.py` uses, and override
`get_session` the same way `tests/test_transit_api.py` overrides it on
the real app - so this remains a genuine HTTP-through-ASGI test, just
against this workstream's own routers in isolation.
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
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from api.transit.realtime.dependencies import get_vehicle_location_provider
from api.transit.realtime.router import router as realtime_router
from api.transit.vehicles.router import router as vehicles_router
from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop, Vehicle  # noqa: E402
from db.session import get_session  # noqa: E402
from simulation.provider import SimulatedVehicleLocationProvider
from simulation.service import SimulationService
from simulation.trip_builder import build_trip_for_route


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


def _test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(vehicles_router, prefix="/api")
    app.include_router(realtime_router, prefix="/api")
    return app


@pytest_asyncio.fixture
async def client(db_session):
    """An httpx AsyncClient against this workstream's own test app, with
    `get_session` overridden (for the roster router) and the realtime
    provider overridden to a `SimulatedVehicleLocationProvider` that
    reuses this same rolled-back `db_session` (mirroring the
    `_session_factory_for` helper in `tests/test_simulation_provider.py`)
    - so live-position requests see exactly what a test set up, and
    nothing is ever committed to the developer's database."""
    from contextlib import asynccontextmanager

    app = _test_app()

    async def override_get_session():
        yield db_session

    @asynccontextmanager
    async def session_factory():
        yield db_session

    def override_get_provider():
        return SimulatedVehicleLocationProvider(session_factory=session_factory)

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_vehicle_location_provider] = override_get_provider
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def running_trip(db_session):
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

    service = SimulationService()
    trip = await build_trip_for_route(
        db_session,
        route.id,
        speed_kmh=1.0,
        scheduled_start_time=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    await service.start_trip(db_session, trip_id=trip.id, vehicle_id=vehicle.id)

    return {"route": route, "vehicle": vehicle, "trip": trip}


# ---------------------------------------------------------------------------
# GET /api/transit/realtime/vehicles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_active_vehicle_positions_empty_when_nothing_running(client):
    response = await client.get("/api/transit/realtime/vehicles")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_active_vehicle_positions_includes_running_vehicle(
    client, running_trip
):
    response = await client.get("/api/transit/realtime/vehicles")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["vehicle_id"] == str(running_trip["vehicle"].id)
    assert body[0]["status"] in ("en_route", "at_stop", "not_started")
    assert "location" in body[0]
    assert "as_of" in body[0]


# ---------------------------------------------------------------------------
# GET /api/transit/realtime/vehicles/{vehicle_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_vehicle_position_returns_position_for_running_vehicle(
    client, running_trip
):
    vehicle_id = running_trip["vehicle"].id
    response = await client.get(f"/api/transit/realtime/vehicles/{vehicle_id}")
    assert response.status_code == 200
    assert response.json()["vehicle_id"] == str(vehicle_id)


@pytest.mark.asyncio
async def test_get_vehicle_position_404_for_nonexistent_vehicle(client):
    response = await client.get(f"/api/transit/realtime/vehicles/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_vehicle_position_422_for_malformed_uuid(client):
    response = await client.get("/api/transit/realtime/vehicles/not-a-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/transit/realtime/routes/{route_id}/vehicles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vehicle_positions_for_route(client, running_trip):
    route_id = running_trip["route"].id
    response = await client.get(f"/api/transit/realtime/routes/{route_id}/vehicles")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["route_id"] == str(route_id)


@pytest.mark.asyncio
async def test_list_vehicle_positions_for_route_empty_for_unrelated_route(
    client, running_trip
):
    response = await client.get(f"/api/transit/realtime/routes/{uuid.uuid4()}/vehicles")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# GET /api/transit/realtime/trips/{trip_id}/vehicles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vehicle_positions_for_trip(client, running_trip):
    trip_id = running_trip["trip"].id
    response = await client.get(f"/api/transit/realtime/trips/{trip_id}/vehicles")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["trip_id"] == str(trip_id)


@pytest.mark.asyncio
async def test_list_vehicle_positions_for_trip_empty_for_nonexistent_trip(client):
    response = await client.get(f"/api/transit/realtime/trips/{uuid.uuid4()}/vehicles")
    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# Roster API: GET /api/transit/vehicles, /api/transit/trips
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_vehicles_returns_seeded_vehicle(client, running_trip):
    response = await client.get("/api/transit/vehicles")
    assert response.status_code == 200
    fleet_numbers = [v["fleet_number"] for v in response.json()]
    assert running_trip["vehicle"].fleet_number in fleet_numbers


@pytest.mark.asyncio
async def test_get_vehicle_detail_404_for_nonexistent_vehicle(client):
    response = await client.get(f"/api/transit/vehicles/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_trips_filters_by_route_id(client, running_trip):
    route_id = running_trip["route"].id
    response = await client.get(
        "/api/transit/trips", params={"route_id": str(route_id)}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(running_trip["trip"].id)


@pytest.mark.asyncio
async def test_list_trips_filters_by_status(client, running_trip):
    response = await client.get("/api/transit/trips", params={"status": "active"})
    assert response.status_code == 200
    assert any(t["id"] == str(running_trip["trip"].id) for t in response.json())

    response = await client.get("/api/transit/trips", params={"status": "completed"})
    assert response.status_code == 200
    assert not any(t["id"] == str(running_trip["trip"].id) for t in response.json())


@pytest.mark.asyncio
async def test_get_trip_detail_404_for_nonexistent_trip(client):
    response = await client.get(f"/api/transit/trips/{uuid.uuid4()}")
    assert response.status_code == 404
