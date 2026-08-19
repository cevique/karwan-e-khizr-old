"""
Phase 6 tests (plan.md section M/H): "frontend integration readiness" -
every public endpoint's response shape matches the documented contract
(section H), CORS headers are present, no authentication is required for
any public transit-data endpoint, and journey-search ride legs carry
`route_geometry` (added this phase - see `api/transit/journey_schemas.py`).

This file does not re-verify behavior already covered elsewhere
(`test_transit_api.py`, `test_journey_api.py`, `test_enhanced_realtime.py`,
`test_trip_generation.py`, ...) - it specifically checks the SHAPE of
what those endpoints return, the CORS contract, and the auth-free
contract, which no existing file asserts explicitly.
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
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from api.graph_state import get_transit_graph  # noqa: E402
from api.transit.realtime.dependencies import get_vehicle_location_provider  # noqa: E402
from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop, Vehicle  # noqa: E402
from db.session import get_session  # noqa: E402
from main import app  # noqa: E402
from routing.graph import build_graph  # noqa: E402
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
async def seeded(db_session):
    """One agency, two routes (one WITH real geometry set directly, one
    WITHOUT - so contract tests cover both the populated and the
    honestly-null `route_geometry`/`geometry` cases), two stops close
    enough to be within walking range of each other and of the search
    origin/destination used below, and a Vehicle for the realtime/ETA
    checks."""
    agency = Agency(name=f"Contract Test Agency {uuid.uuid4()}", network_type="brt")
    db_session.add(agency)
    await db_session.flush()

    route_with_geometry = Route(
        agency_id=agency.id,
        short_name="CT-GEO",
        long_name="Contract Test Route With Geometry",
        color="#1E88E5",
        path="SRID=4326;LINESTRING(73.0000 33.0000, 73.0500 33.0000, 73.1000 33.0000)",
    )
    route_without_geometry = Route(
        agency_id=agency.id,
        short_name="CT-NOGEO",
        long_name="Contract Test Route Without Geometry",
        color="#43A047",
    )
    db_session.add_all([route_with_geometry, route_without_geometry])
    await db_session.flush()

    stop_a = Stop(name="Contract Stop A", location="SRID=4326;POINT(73.0000 33.0000)")
    stop_b = Stop(name="Contract Stop B", location="SRID=4326;POINT(73.1000 33.0000)")
    db_session.add_all([stop_a, stop_b])
    await db_session.flush()

    db_session.add_all(
        [
            RouteStop(route_id=route_with_geometry.id, stop_id=stop_a.id, sequence=1),
            RouteStop(route_id=route_with_geometry.id, stop_id=stop_b.id, sequence=2),
        ]
    )
    await db_session.flush()

    vehicle = Vehicle(fleet_number=f"CT-BUS-{uuid.uuid4().hex[:6]}")
    db_session.add(vehicle)
    await db_session.flush()

    service = SimulationService()
    scheduled_start_time = datetime.now(timezone.utc) - timedelta(seconds=5)
    trip = await build_trip_for_route(
        db_session,
        route_with_geometry.id,
        speed_kmh=1.0,
        scheduled_start_time=scheduled_start_time,
    )
    await service.start_trip(
        db_session, trip_id=trip.id, vehicle_id=vehicle.id, start_time=scheduled_start_time
    )

    return {
        "agency": agency,
        "route_with_geometry": route_with_geometry,
        "route_without_geometry": route_without_geometry,
        "stop_a": stop_a,
        "stop_b": stop_b,
        "vehicle": vehicle,
        "trip": trip,
    }


@pytest_asyncio.fixture
async def client(db_session, seeded):
    graph = await build_graph(db_session)

    async def override_get_session():
        yield db_session

    def override_get_transit_graph():
        return graph

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def session_factory():
        yield db_session

    def override_get_provider():
        return SimulatedVehicleLocationProvider(session_factory=session_factory)

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_transit_graph] = override_get_transit_graph
    app.dependency_overrides[get_vehicle_location_provider] = override_get_provider
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_transit_graph, None)
        app.dependency_overrides.pop(get_vehicle_location_provider, None)


def _journey_search_body(seeded):
    return {
        "origin": {"latitude": 33.0000, "longitude": 73.0000},
        "destination": {"latitude": 33.0000, "longitude": 73.1000},
        "objective": "fastest",
        "max_walk_m": 50.0,
    }


# ---------------------------------------------------------------------------
# Section H item 1: static transit data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agencies_endpoint_matches_documented_shape(client, seeded):
    response = await client.get("/api/transit/agencies")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    entry = next(a for a in body if a["id"] == str(seeded["agency"].id))
    assert {"id", "name", "network_type"}.issubset(entry.keys())


@pytest.mark.asyncio
async def test_routes_list_endpoint_matches_documented_shape(client, seeded):
    response = await client.get("/api/transit/routes")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    entry = next(r for r in body if r["id"] == str(seeded["route_with_geometry"].id))
    assert {"id", "short_name", "long_name", "color", "agency_id"}.issubset(entry.keys())


@pytest.mark.asyncio
async def test_route_detail_matches_documented_shape_with_geometry(client, seeded):
    route_id = seeded["route_with_geometry"].id
    response = await client.get(f"/api/transit/routes/{route_id}")
    assert response.status_code == 200
    body = response.json()
    assert {"id", "short_name", "color", "geometry", "stops"}.issubset(body.keys())
    assert body["geometry"]["type"] == "LineString"
    assert isinstance(body["geometry"]["coordinates"], list)
    assert len(body["geometry"]["coordinates"]) >= 2
    # GeoJSON order: [longitude, latitude].
    first_lon, first_lat = body["geometry"]["coordinates"][0]
    assert first_lon == pytest.approx(73.0)
    assert first_lat == pytest.approx(33.0)
    assert len(body["stops"]) == 2


@pytest.mark.asyncio
async def test_route_detail_matches_documented_shape_without_geometry(client, seeded):
    route_id = seeded["route_without_geometry"].id
    response = await client.get(f"/api/transit/routes/{route_id}")
    assert response.status_code == 200
    body = response.json()
    # Explicitly null, not absent, not a fabricated straight line.
    assert body["geometry"]["type"] is None
    assert body["geometry"]["coordinates"] is None


@pytest.mark.asyncio
async def test_route_geometry_standalone_endpoint_matches_documented_shape(client, seeded):
    route_id = seeded["route_with_geometry"].id
    response = await client.get(f"/api/transit/routes/{route_id}/geometry")
    assert response.status_code == 200
    body = response.json()
    assert {"type", "coordinates", "geometry_source", "geometry_confidence"}.issubset(
        body.keys()
    )
    assert body["type"] == "LineString"


@pytest.mark.asyncio
async def test_stops_endpoint_matches_documented_shape(client, seeded):
    response = await client.get("/api/transit/stops")
    assert response.status_code == 200
    body = response.json()
    entry = next(s for s in body if s["id"] == str(seeded["stop_a"].id))
    assert {"id", "name", "location"}.issubset(entry.keys())
    assert {"latitude", "longitude"}.issubset(entry["location"].keys())


@pytest.mark.asyncio
async def test_nearby_stops_query_includes_distance_m(client, seeded):
    response = await client.get(
        "/api/transit/stops",
        params={"latitude": 33.0000, "longitude": 73.0000, "radius_m": 5000},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    for stop in body:
        assert "distance_m" in stop
        assert stop["distance_m"] is None or isinstance(stop["distance_m"], (int, float))


# ---------------------------------------------------------------------------
# Section H item 3/4/5: realtime vehicles and ETAs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_realtime_vehicles_matches_documented_shape(client, seeded):
    response = await client.get("/api/transit/realtime/vehicles")
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    position = next(p for p in body if p["vehicle_id"] == str(seeded["vehicle"].id))
    required_keys = {
        "vehicle_id",
        "route_id",
        "route_short_name",
        "route_color",
        "location",
        "bearing",
        "status",
        "current_stop_name",
        "next_stop_name",
        "scheduled_arrival_next_stop",
        "estimated_arrival_next_stop",
        "delay_seconds",
    }
    assert required_keys.issubset(position.keys())
    assert {"latitude", "longitude"}.issubset(position["location"].keys())


@pytest.mark.asyncio
async def test_realtime_vehicle_detail_same_shape_as_list(client, seeded):
    vehicle_id = seeded["vehicle"].id
    response = await client.get(f"/api/transit/realtime/vehicles/{vehicle_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["vehicle_id"] == str(vehicle_id)


@pytest.mark.asyncio
async def test_realtime_route_vehicles_matches_documented_shape(client, seeded):
    route_id = seeded["route_with_geometry"].id
    response = await client.get(f"/api/transit/realtime/routes/{route_id}/vehicles")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    if body:
        assert body[0]["route_id"] == str(route_id)


@pytest.mark.asyncio
async def test_realtime_eta_matches_documented_shape(client, seeded):
    vehicle_id = seeded["vehicle"].id
    response = await client.get(f"/api/transit/realtime/vehicles/{vehicle_id}/eta")
    assert response.status_code == 200
    body = response.json()
    assert {"vehicle_id", "trip_id", "etas"}.issubset(body.keys())
    for eta in body["etas"]:
        assert {"stop_id", "stop_name", "sequence", "scheduled_arrival", "estimated_arrival", "delay_seconds"}.issubset(
            eta.keys()
        )


# ---------------------------------------------------------------------------
# Section H item 6 (Phase 6 addition): route_geometry per ride leg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_journey_search_ride_leg_includes_route_geometry_when_present(client, seeded):
    response = await client.post(
        "/api/transit/journeys/search", json=_journey_search_body(seeded)
    )
    assert response.status_code == 200
    journeys = response.json()["journeys"]
    assert len(journeys) == 1
    ride_legs = [leg for leg in journeys[0]["legs"] if leg["type"] == "ride"]
    assert len(ride_legs) == 1
    ride_leg = ride_legs[0]

    assert "route_geometry" in ride_leg
    assert ride_leg["route_geometry"]["type"] == "LineString"
    assert isinstance(ride_leg["route_geometry"]["coordinates"], list)
    assert len(ride_leg["route_geometry"]["coordinates"]) >= 2
    # This is the route's FULL geometry, not a cropped sub-path (see
    # RideLegRead's docstring) - same 3 vertices as the raw route.
    assert len(ride_leg["route_geometry"]["coordinates"]) == 3


@pytest.mark.asyncio
async def test_journey_search_ride_leg_route_geometry_is_null_when_route_has_none(
    client, db_session, seeded
):
    """A route with no `path` generated yet must produce a null
    (not missing, not fabricated) `route_geometry` on its ride leg -
    exercised by routing a search through `route_without_geometry`."""
    stop_c = Stop(name="Contract Stop C", location="SRID=4326;POINT(73.2000 33.0000)")
    db_session.add(stop_c)
    await db_session.flush()
    db_session.add_all(
        [
            RouteStop(
                route_id=seeded["route_without_geometry"].id,
                stop_id=seeded["stop_b"].id,
                sequence=1,
            ),
            RouteStop(
                route_id=seeded["route_without_geometry"].id, stop_id=stop_c.id, sequence=2
            ),
        ]
    )
    await db_session.flush()
    # `client`'s fixture already built a graph from `db_session` once
    # (before this route_stops insert); SQLAlchemy's identity map can
    # otherwise leave `route_without_geometry`'s already-loaded (empty)
    # `.route_stops` relationship stale on the SECOND `build_graph` call
    # below, even though the new rows are flushed - expire just that one
    # relationship (not the whole identity map, which would also force a
    # later lazy-load of `.agency` outside an async context) so the
    # rebuild re-reads it from the database. This is a test-only concern
    # (a real request builds/uses the graph once per session);
    # `routing.graph.build_graph` itself needs no change for this.
    db_session.expire(seeded["route_without_geometry"], ["route_stops"])

    from sqlalchemy import select as _select

    rs_check = (
        await db_session.execute(
            _select(RouteStop).where(
                RouteStop.route_id == seeded["route_without_geometry"].id
            )
        )
    ).scalars().all()
    assert len(rs_check) == 2

    from routing.graph import build_graph as _build_graph

    graph = await _build_graph(db_session)

    def override_get_transit_graph():
        return graph

    app.dependency_overrides[get_transit_graph] = override_get_transit_graph

    body = {
        "origin": {"latitude": 33.0000, "longitude": 73.1000},
        "destination": {"latitude": 33.0000, "longitude": 73.2000},
        "objective": "fastest",
        "max_walk_m": 50.0,
    }
    response = await client.post("/api/transit/journeys/search", json=body)
    assert response.status_code == 200
    journeys = response.json()["journeys"]
    assert len(journeys) == 1
    ride_legs = [leg for leg in journeys[0]["legs"] if leg["type"] == "ride"]
    assert len(ride_legs) == 1
    assert ride_legs[0]["route_geometry"]["type"] is None
    assert ride_legs[0]["route_geometry"]["coordinates"] is None


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cors_headers_present_on_a_public_get_endpoint(client, seeded):
    response = await client.get(
        "/api/transit/agencies", headers={"Origin": "https://example-frontend.test"}
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"


@pytest.mark.asyncio
async def test_cors_preflight_request_is_allowed(client, seeded):
    response = await client.options(
        "/api/transit/journeys/search",
        headers={
            "Origin": "https://example-frontend.test",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"
    assert "POST" in response.headers.get("access-control-allow-methods", "")


# ---------------------------------------------------------------------------
# No authentication required for public transit data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_public_endpoints_require_no_authentication(client, seeded):
    """Every endpoint plan.md section H documents as part of the public
    map/frontend contract must work with NO Authorization header at all -
    `client` here never sets one anywhere in this file."""
    vehicle_id = seeded["vehicle"].id
    route_id = seeded["route_with_geometry"].id

    get_requests = [
        "/api/transit/agencies",
        "/api/transit/routes",
        f"/api/transit/routes/{route_id}",
        f"/api/transit/routes/{route_id}/geometry",
        "/api/transit/stops",
        "/api/transit/realtime/vehicles",
        f"/api/transit/realtime/vehicles/{vehicle_id}",
        f"/api/transit/realtime/vehicles/{vehicle_id}/eta",
        f"/api/transit/realtime/routes/{route_id}/vehicles",
    ]
    for path in get_requests:
        response = await client.get(path)
        assert response.status_code not in (401, 403), f"{path} unexpectedly required auth"

    response = await client.post(
        "/api/transit/journeys/search", json=_journey_search_body(seeded)
    )
    assert response.status_code not in (401, 403)


@pytest.mark.asyncio
async def test_admin_endpoints_still_require_authentication(client, seeded):
    """The auth-free contract is specifically for PUBLIC transit data -
    `/admin/*` must remain gated (regression guard: Phase 6 must not
    accidentally loosen this while making other endpoints public)."""
    response = await client.post(
        "/api/admin/trips/generate",
        json={"route_id": str(seeded["route_with_geometry"].id), "service_date": "2026-09-01"},
    )
    assert response.status_code == 401
