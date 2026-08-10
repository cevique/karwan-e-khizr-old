"""
Tests for the static transit-network API (`api/transit/router.py`).

Reuses the same `db_session` transaction/SAVEPOINT-rollback pattern as
`tests/test_transit_models.py` (a real AsyncSession bound to the
application's own `DATABASE_URL`, nested inside a transaction that is
always rolled back), so nothing here ever persists to the developer's
database. Skipped (not failed) if that database isn't reachable, matching
the existing test suite's convention.

The FastAPI app under test has its `get_session` dependency overridden to
yield this same rolled-back session, so HTTP requests made through the
`httpx.ASGITransport` client see the exact rows each test set up.
"""

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
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop  # noqa: E402
from db.session import get_session  # noqa: E402
from main import app  # noqa: E402


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
    """Same pattern as tests/test_transit_models.py's fixture of the same
    name: a real AsyncSession, nested in a transaction that's always rolled
    back on teardown, so nothing committed here persists."""
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
    """An httpx AsyncClient wired to the real app, with `get_session`
    overridden to yield the rolled-back `db_session` above, so requests
    see exactly the rows a test set up and nothing is ever committed."""

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest_asyncio.fixture
async def seeded(db_session):
    """One agency, one route, three stops in sequence order 1/2/3."""
    agency = Agency(name=f"Test Agency {uuid.uuid4()}", network_type="brt")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="T-1", long_name="Test Route")
    db_session.add(route)
    await db_session.flush()

    stop_1 = Stop(name="Alpha Stop", location="SRID=4326;POINT(73.0479 33.6844)")
    stop_2 = Stop(name="Beta Stop", location="SRID=4326;POINT(73.0551 33.6938)")
    stop_3 = Stop(name="Gamma Stop", location="SRID=4326;POINT(73.0700 33.7100)")
    db_session.add_all([stop_1, stop_2, stop_3])
    await db_session.flush()

    db_session.add_all(
        [
            RouteStop(route_id=route.id, stop_id=stop_1.id, sequence=1),
            RouteStop(route_id=route.id, stop_id=stop_2.id, sequence=2),
            RouteStop(route_id=route.id, stop_id=stop_3.id, sequence=3),
        ]
    )
    await db_session.flush()

    return {
        "agency": agency,
        "route": route,
        "stops": [stop_1, stop_2, stop_3],
    }


# ---------------------------------------------------------------------------
# Agencies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_agencies_returns_seeded_agency(client, seeded):
    response = await client.get("/api/transit/agencies")
    assert response.status_code == 200
    body = response.json()
    assert any(a["id"] == str(seeded["agency"].id) for a in body)
    match = next(a for a in body if a["id"] == str(seeded["agency"].id))
    assert match["name"] == seeded["agency"].name
    assert match["network_type"] == "brt"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_routes_returns_seeded_route(client, seeded):
    response = await client.get("/api/transit/routes")
    assert response.status_code == 200
    body = response.json()
    assert any(r["id"] == str(seeded["route"].id) for r in body)


@pytest.mark.asyncio
async def test_list_routes_filters_by_agency_id(client, seeded):
    response = await client.get(
        "/api/transit/routes", params={"agency_id": str(seeded["agency"].id)}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) >= 1
    assert all(r["agency_id"] == str(seeded["agency"].id) for r in body)

    other_agency_id = uuid.uuid4()
    response = await client.get(
        "/api/transit/routes", params={"agency_id": str(other_agency_id)}
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_route_detail_includes_agency_and_ordered_stops(client, seeded):
    route = seeded["route"]
    stops = seeded["stops"]

    response = await client.get(f"/api/transit/routes/{route.id}")
    assert response.status_code == 200
    body = response.json()

    assert body["id"] == str(route.id)
    assert body["short_name"] == "T-1"
    assert body["agency"]["id"] == str(seeded["agency"].id)

    assert [s["sequence"] for s in body["stops"]] == [1, 2, 3]
    assert [s["stop"]["id"] for s in body["stops"]] == [str(s.id) for s in stops]

    first_stop_location = body["stops"][0]["stop"]["location"]
    assert first_stop_location["longitude"] == pytest.approx(73.0479, abs=1e-3)
    assert first_stop_location["latitude"] == pytest.approx(33.6844, abs=1e-3)


@pytest.mark.asyncio
async def test_get_route_detail_404_for_nonexistent_route(client):
    response = await client.get(f"/api/transit/routes/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_route_detail_422_for_invalid_uuid(client):
    response = await client.get("/api/transit/routes/not-a-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Stops
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_stops_returns_seeded_stops_with_coordinates(client, seeded):
    response = await client.get("/api/transit/stops")
    assert response.status_code == 200
    body = response.json()

    seeded_ids = {str(s.id) for s in seeded["stops"]}
    returned = {s["id"]: s for s in body if s["id"] in seeded_ids}
    assert seeded_ids == set(returned.keys())

    alpha = next(s for s in body if s["name"] == "Alpha Stop")
    assert alpha["location"]["longitude"] == pytest.approx(73.0479, abs=1e-3)
    assert alpha["location"]["latitude"] == pytest.approx(33.6844, abs=1e-3)
    assert alpha["distance_m"] is None


@pytest.mark.asyncio
async def test_get_stop_detail(client, seeded):
    stop = seeded["stops"][0]
    response = await client.get(f"/api/transit/stops/{stop.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(stop.id)
    assert body["name"] == "Alpha Stop"
    assert body["distance_m"] is None


@pytest.mark.asyncio
async def test_get_stop_detail_404_for_nonexistent_stop(client):
    response = await client.get(f"/api/transit/stops/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_nearby_stops_query_returns_expected_stops_ordered_by_distance(
    client, seeded
):
    # Centered essentially on stop 1 (Alpha), with a radius that reaches
    # stop 2 (Beta, ~1.3km away) but not stop 3 (Gamma, ~9km away).
    response = await client.get(
        "/api/transit/stops",
        params={"latitude": 33.6844, "longitude": 73.0479, "radius_m": 2000},
    )
    assert response.status_code == 200
    body = response.json()

    names = [s["name"] for s in body]
    assert "Alpha Stop" in names
    assert "Beta Stop" in names
    assert "Gamma Stop" not in names

    # Nearest first.
    alpha_index = names.index("Alpha Stop")
    beta_index = names.index("Beta Stop")
    assert alpha_index < beta_index

    for s in body:
        assert s["distance_m"] is not None
        assert s["distance_m"] >= 0


@pytest.mark.asyncio
async def test_nearby_stops_query_requires_all_three_params(client):
    response = await client.get(
        "/api/transit/stops", params={"latitude": 33.6844, "longitude": 73.0479}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_nearby_stops_query_rejects_invalid_latitude(client):
    response = await client.get(
        "/api/transit/stops",
        params={"latitude": 200, "longitude": 73.0479, "radius_m": 500},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_nearby_stops_query_rejects_radius_over_the_cap(client):
    response = await client.get(
        "/api/transit/stops",
        params={"latitude": 33.6844, "longitude": 73.0479, "radius_m": 50_000},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_endpoints_respect_limit(client, seeded):
    response = await client.get("/api/transit/stops", params={"limit": 1})
    assert response.status_code == 200
    assert len(response.json()) <= 1


@pytest.mark.asyncio
async def test_limit_over_the_cap_is_rejected(client):
    response = await client.get("/api/transit/stops", params={"limit": 10_000})
    assert response.status_code == 422
