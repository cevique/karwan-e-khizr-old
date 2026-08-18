"""
Phase 4 tests (plan.md section M): the enhanced realtime vehicle-position
API (bearing, stop names, route metadata, ETA/delay) and the new
per-vehicle ETA endpoint.

Uses the real `main.app` (unlike `tests/test_realtime_api.py`'s isolated
mini-app) with only `get_session` overridden - `api/transit/realtime/
router.py`, `eta_router.py`, and `control_router.py` are all genuinely
mounted on it (see `api/router.py`), so this also exercises that they're
wired up correctly, not just that the underlying functions work.
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

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from api.transit.realtime.dependencies import get_vehicle_location_provider  # noqa: E402
from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop, Vehicle  # noqa: E402
from db.session import get_session  # noqa: E402
from main import app  # noqa: E402
from simulation.provider import SimulatedVehicleLocationProvider  # noqa: E402
from simulation.service import SimulationService  # noqa: E402
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
    """Same savepoint/rollback fixture as the rest of the suite."""
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
    """Against the real `main.app`, `get_session` AND the vehicle-location
    provider both overridden to reuse this same rolled-back `db_session` -
    mirrors `tests/test_realtime_api.py`'s `_session_factory_for` pattern
    so nothing this test writes is ever actually committed."""
    from contextlib import asynccontextmanager

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
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_vehicle_location_provider, None)


async def _make_running_trip(
    db_session,
    *,
    stop_a_location: str = "SRID=4326;POINT(73.0000 33.0000)",
    stop_b_location: str = "SRID=4326;POINT(73.1000 33.0000)",
    speed_kmh: float = 1.0,
    started_seconds_ago: float = 30.0,
    route_path: str | None = None,
):
    """Build and start a 2-stop trip, same shape as
    `tests/test_realtime_api.py::running_trip` but as a plain async
    helper (not a fixture) so individual tests can vary the geometry/
    timing per case."""
    agency = Agency(name=f"Enhanced Realtime Test Agency {uuid.uuid4()}", network_type="brt")
    db_session.add(agency)
    await db_session.flush()

    route = Route(
        agency_id=agency.id,
        short_name="T-1",
        long_name="Test Route",
        color="#E53935",
        path=route_path,
    )
    db_session.add(route)
    await db_session.flush()

    stop_a = Stop(name="Stop A", location=stop_a_location)
    stop_b = Stop(name="Stop B", location=stop_b_location)
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
    scheduled_start_time = datetime.now(timezone.utc) - timedelta(seconds=started_seconds_ago)
    trip = await build_trip_for_route(
        db_session,
        route.id,
        speed_kmh=speed_kmh,
        scheduled_start_time=scheduled_start_time,
    )
    # `start_trip` defaults `start_time` to "now" itself if not given
    # explicitly - pass the same instant `build_trip_for_route` was
    # given so `started_seconds_ago` actually takes effect.
    await service.start_trip(
        db_session, trip_id=trip.id, vehicle_id=vehicle.id, start_time=scheduled_start_time
    )

    return {
        "agency": agency,
        "route": route,
        "vehicle": vehicle,
        "trip": trip,
        "stop_a": stop_a,
        "stop_b": stop_b,
    }


# ---------------------------------------------------------------------------
# GET /api/transit/realtime/vehicles - enhanced fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vehicle_position_includes_route_and_stop_metadata(client, db_session):
    running = await _make_running_trip(db_session)
    response = await client.get("/api/transit/realtime/vehicles")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    position = body[0]

    assert position["route_short_name"] == "T-1"
    assert position["route_color"] == "#E53935"
    # En route (or at a stop) between Stop A and Stop B - whichever it
    # currently is, both names must resolve, not stay null/UUID-only.
    assert position["current_stop_name"] in ("Stop A", "Stop B")
    if position["next_stop_id"] is not None:
        assert position["next_stop_name"] in ("Stop A", "Stop B")


@pytest.mark.asyncio
async def test_vehicle_position_bearing_faces_east_on_eastbound_route(client, db_session):
    # Stop A -> Stop B is due east (same latitude, increasing longitude).
    await _make_running_trip(db_session, speed_kmh=1.0, started_seconds_ago=5.0)
    response = await client.get("/api/transit/realtime/vehicles")
    assert response.status_code == 200
    position = response.json()[0]
    assert position["bearing"] is not None
    assert position["bearing"] == pytest.approx(90.0, abs=1.0)


@pytest.mark.asyncio
async def test_vehicle_position_speed_kmh_present_and_nonnegative(client, db_session):
    await _make_running_trip(db_session)
    response = await client.get("/api/transit/realtime/vehicles")
    position = response.json()[0]
    assert position["speed_kmh"] is not None
    assert position["speed_kmh"] >= 0.0


@pytest.mark.asyncio
async def test_vehicle_position_delay_is_zero_for_simulated_vehicle(client, db_session):
    """plan.md section I: a simulated vehicle IS the schedule - delay
    must always be exactly 0, never a nonzero or missing value, whenever
    there's a next stop to report a delay against."""
    await _make_running_trip(db_session)
    response = await client.get("/api/transit/realtime/vehicles")
    position = response.json()[0]
    if position["next_stop_id"] is not None:
        assert position["delay_seconds"] == 0.0
        assert position["scheduled_arrival_next_stop"] is not None
        assert position["estimated_arrival_next_stop"] is not None
        assert (
            position["estimated_arrival_next_stop"] == position["scheduled_arrival_next_stop"]
        )


@pytest.mark.asyncio
async def test_vehicle_position_completed_trip_has_no_next_stop_fields(client, db_session):
    """A trip that's already finished (scheduled start far enough in the
    past that elapsed_s exceeds the last stop's arrival) has
    `next_stop_id is None`, so bearing/next-stop/ETA/delay must all be
    null - not stale or fabricated values from the last real leg."""
    await _make_running_trip(db_session, speed_kmh=1000.0, started_seconds_ago=9999.0)
    response = await client.get("/api/transit/realtime/vehicles")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    position = body[0]
    assert position["status"] == "completed"
    assert position["next_stop_id"] is None
    assert position["bearing"] is None
    assert position["next_stop_name"] is None
    assert position["scheduled_arrival_next_stop"] is None
    assert position["estimated_arrival_next_stop"] is None
    assert position["delay_seconds"] is None
    assert position["speed_kmh"] == 0.0


@pytest.mark.asyncio
async def test_vehicle_position_follows_route_geometry_when_present(client, db_session):
    """Wiring test: `simulation.provider._load_route_geometry` actually
    loads a real `Route.path` set directly in the DB and passes it
    through - the resulting en-route position should differ from the
    straight stop-to-stop line, matching what
    `tests/test_engine_geometry_interpolation.py` proves the pure engine
    logic does."""
    bending_path = "SRID=4326;LINESTRING(73.0000 33.0000, 73.0000 33.0200, 73.1000 33.0200, 73.1000 33.0000)"
    await _make_running_trip(
        db_session, speed_kmh=1.0, started_seconds_ago=5.0, route_path=bending_path
    )
    response = await client.get("/api/transit/realtime/vehicles")
    assert response.status_code == 200
    position = response.json()[0]

    # Straight-line stop A -> stop B is due east (bearing ~90). Early on
    # the bending polyline above, the bus is heading north first
    # (bearing ~0) before turning east - so the reported bearing should
    # NOT be ~90 here, proving the polyline (not the straight chord) was
    # actually used.
    if position["status"] == "en_route":
        assert position["bearing"] is not None
        assert position["bearing"] != pytest.approx(90.0, abs=10.0)


@pytest.mark.asyncio
async def test_vehicle_position_still_works_when_route_has_no_geometry(client, db_session):
    """The overwhelmingly common real-data case today (plan.md's Phase 3
    handoff: 0 real routes have geometry yet) - must behave exactly as
    before Phase 4, not error or omit fields."""
    await _make_running_trip(db_session, route_path=None)
    response = await client.get("/api/transit/realtime/vehicles")
    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_list_active_vehicle_positions_still_empty_when_nothing_running(client):
    response = await client.get("/api/transit/realtime/vehicles")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_vehicle_position_single_lookup_has_enhanced_fields(client, db_session):
    running = await _make_running_trip(db_session)
    vehicle_id = running["vehicle"].id
    response = await client.get(f"/api/transit/realtime/vehicles/{vehicle_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle_id"] == str(vehicle_id)
    assert body["route_short_name"] == "T-1"


# ---------------------------------------------------------------------------
# GET /api/transit/realtime/vehicles/{id}/eta
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_vehicle_eta_404_for_nonexistent_vehicle(client):
    response = await client.get(f"/api/transit/realtime/vehicles/{uuid.uuid4()}/eta")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_vehicle_eta_returns_upcoming_stops_in_sequence_order(client, db_session):
    running = await _make_running_trip(db_session, speed_kmh=1.0, started_seconds_ago=5.0)
    vehicle_id = running["vehicle"].id

    response = await client.get(f"/api/transit/realtime/vehicles/{vehicle_id}/eta")
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle_id"] == str(vehicle_id)
    assert body["trip_id"] == str(running["trip"].id)

    etas = body["etas"]
    assert len(etas) >= 1
    sequences = [e["sequence"] for e in etas]
    assert sequences == sorted(sequences)
    for eta in etas:
        assert eta["delay_seconds"] == 0.0
        assert eta["estimated_arrival"] == eta["scheduled_arrival"]
        assert eta["stop_name"] in ("Stop A", "Stop B")


@pytest.mark.asyncio
async def test_get_vehicle_eta_empty_for_completed_trip(client, db_session):
    running = await _make_running_trip(db_session, speed_kmh=1000.0, started_seconds_ago=9999.0)
    vehicle_id = running["vehicle"].id

    response = await client.get(f"/api/transit/realtime/vehicles/{vehicle_id}/eta")
    assert response.status_code == 200
    body = response.json()
    assert body["etas"] == []


@pytest.mark.asyncio
async def test_get_vehicle_eta_scheduled_arrival_matches_stop_time_offset(client, db_session):
    """Cross-check: the ETA's `scheduled_arrival` for the final stop must
    equal `scheduled_start_time + StopTime.arrival_offset_s` for that
    stop - not an approximation."""
    running = await _make_running_trip(db_session, speed_kmh=1.0, started_seconds_ago=5.0)
    vehicle_id = running["vehicle"].id
    trip = running["trip"]

    from sqlalchemy import select

    from db.models import StopTime

    result = await db_session.execute(
        select(StopTime).where(StopTime.trip_id == trip.id).order_by(StopTime.sequence)
    )
    stop_times = list(result.scalars())
    last_stop_time = stop_times[-1]
    expected_arrival = trip.scheduled_start_time + timedelta(
        seconds=last_stop_time.arrival_offset_s
    )

    response = await client.get(f"/api/transit/realtime/vehicles/{vehicle_id}/eta")
    body = response.json()
    last_eta = next(e for e in body["etas"] if e["stop_id"] == str(last_stop_time.stop_id))
    actual_arrival = datetime.fromisoformat(last_eta["scheduled_arrival"])
    assert actual_arrival == expected_arrival
