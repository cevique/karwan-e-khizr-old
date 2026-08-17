"""
Phase 3 tests (plan.md section M): road-following route geometry
generation via OSRM road-snapping.

Three layers, mirroring `tests/test_geocoding.py`'s structure:

1. Pure `seeding.route_geometry` logic (no network, no database):
   - `linestring_wkt`/`cumulative_distances_m` helpers
   - `OSRMRouteGeometryProvider` against a mocked HTTP transport
     (`httpx.MockTransport` - no real network access, matching plan.md
     section L's testing strategy for the geocoding equivalent)

2. `scripts.generate_route_geometry.generate_route_geometry` against a
   fake `RouteGeometryProvider` (real database, no real network):
   eligibility (>=2 stops, all located), provenance tagging, failure
   handling, `--dry-run`/`--limit` behavior, and that `RouteStop.
   distance_along_route_m` is populated from cumulative leg distances.

3. The `GET /transit/routes/{id}` and `GET /transit/routes/{id}/geometry`
   API endpoints: geometry embedded/served as GeoJSON, and the explicit
   null-geometry shape for a route with no `path` yet.
"""

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop  # noqa: E402
from db.session import get_session  # noqa: E402
from main import app  # noqa: E402
from seeding.route_geometry import (  # noqa: E402
    OSRMRouteGeometryProvider,
    RouteGeometryError,
    RouteGeometryResult,
    cumulative_distances_m,
    linestring_wkt,
)

# ---------------------------------------------------------------------------
# Pure: linestring_wkt / cumulative_distances_m
# ---------------------------------------------------------------------------


def test_linestring_wkt_formats_lon_lat_pairs():
    wkt = linestring_wkt([(73.05, 33.68), (73.06, 33.69), (73.07, 33.70)])
    assert wkt == "SRID=4326;LINESTRING(73.05 33.68, 73.06 33.69, 73.07 33.7)"


def test_cumulative_distances_m_starts_at_zero_and_accumulates():
    assert cumulative_distances_m([100.0, 250.0, 50.0]) == (0.0, 100.0, 350.0, 400.0)


def test_cumulative_distances_m_empty_legs_is_single_zero():
    assert cumulative_distances_m([]) == (0.0,)


# ---------------------------------------------------------------------------
# Pure: OSRMRouteGeometryProvider against a mocked HTTP transport
# ---------------------------------------------------------------------------


def _osrm_payload(coordinates: list[tuple[float, float]], leg_distances: list[float]) -> dict:
    return {
        "code": "Ok",
        "routes": [
            {
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "legs": [{"distance": d} for d in leg_distances],
            }
        ],
    }


@pytest.mark.asyncio
async def test_osrm_provider_returns_geometry_and_leg_distances():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "73.05,33.68;73.07,33.7" in str(request.url)
        assert request.url.params["overview"] == "full"
        assert request.url.params["geometries"] == "geojson"
        return httpx.Response(
            200,
            json=_osrm_payload(
                [[73.05, 33.68], [73.06, 33.69], [73.07, 33.70]], [120.5, 340.2]
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with OSRMRouteGeometryProvider(client) as provider:
        result = await provider.route([(33.68, 73.05), (33.70, 73.07)])

    assert result == RouteGeometryResult(
        coordinates=((73.05, 33.68), (73.06, 33.69), (73.07, 33.70)),
        leg_distances_m=(120.5, 340.2),
    )


@pytest.mark.asyncio
async def test_osrm_provider_raises_on_non_ok_code():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"code": "NoRoute", "message": "no route found"})
        )
    )
    async with OSRMRouteGeometryProvider(client) as provider:
        with pytest.raises(RouteGeometryError):
            await provider.route([(33.68, 73.05), (33.70, 73.07)])


@pytest.mark.asyncio
async def test_osrm_provider_raises_on_http_failure():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503, text="Service Unavailable"))
    )
    async with OSRMRouteGeometryProvider(client) as provider:
        with pytest.raises(RouteGeometryError):
            await provider.route([(33.68, 73.05), (33.70, 73.07)])


@pytest.mark.asyncio
async def test_osrm_provider_raises_on_empty_routes():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"code": "Ok", "routes": []}))
    )
    async with OSRMRouteGeometryProvider(client) as provider:
        with pytest.raises(RouteGeometryError):
            await provider.route([(33.68, 73.05), (33.70, 73.07)])


@pytest.mark.asyncio
async def test_osrm_provider_rejects_too_few_waypoints():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    async with OSRMRouteGeometryProvider(client) as provider:
        with pytest.raises(RouteGeometryError):
            await provider.route([(33.68, 73.05)])


# ---------------------------------------------------------------------------
# Integration: real PostgreSQL/PostGIS, rolled back on teardown
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
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


class FakeRouteGeometryProvider:
    """Deterministic `RouteGeometryProvider` for tests: returns a canned
    `RouteGeometryResult` (or raises `RouteGeometryError`) per exact
    waypoint tuple, and records every call it received."""

    def __init__(self, responses: dict[tuple, RouteGeometryResult]):
        self._responses = responses
        self.calls: list[tuple] = []

    async def route(self, waypoints):
        key = tuple(waypoints)
        self.calls.append(key)
        if key not in self._responses:
            raise RouteGeometryError(f"no canned response for {key!r}")
        return self._responses[key]


async def _make_route(
    session, *, agency_name: str, short_name: str, stop_locations: list[str | None]
) -> tuple[Route, list[Stop]]:
    agency = Agency(name=agency_name, network_type="brt")
    session.add(agency)
    await session.flush()

    route = Route(agency_id=agency.id, short_name=short_name)
    session.add(route)
    await session.flush()

    stops = []
    for i, location in enumerate(stop_locations, start=1):
        stop = Stop(name=f"{short_name} Stop {i}", location=location)
        session.add(stop)
        stops.append(stop)
    await session.flush()

    for i, stop in enumerate(stops, start=1):
        session.add(RouteStop(route_id=route.id, stop_id=stop.id, sequence=i))
    await session.flush()

    return route, stops


@pytest.mark.asyncio
async def test_generate_route_geometry_populates_path_and_distances(db_session):
    from scripts.generate_route_geometry import generate_route_geometry

    agency_name = f"Geometry Test Agency {uuid.uuid4()}"
    route, stops = await _make_route(
        db_session,
        agency_name=agency_name,
        short_name=f"GEO-{uuid.uuid4().hex[:6]}",
        stop_locations=[
            "SRID=4326;POINT(73.05 33.68)",
            "SRID=4326;POINT(73.06 33.69)",
            "SRID=4326;POINT(73.07 33.70)",
        ],
    )

    waypoints = ((33.68, 73.05), (33.69, 73.06), (33.70, 73.07))
    provider = FakeRouteGeometryProvider(
        {
            waypoints: RouteGeometryResult(
                coordinates=((73.05, 33.68), (73.055, 33.685), (73.06, 33.69), (73.07, 33.70)),
                leg_distances_m=(150.0, 200.0),
            )
        }
    )

    stats = await generate_route_geometry(db_session, provider)
    assert stats == {"eligible": 1, "generated": 1, "failed": 0}

    refreshed = (await db_session.execute(select(Route).where(Route.id == route.id))).scalar_one()
    assert refreshed.geometry_source == "OSRM"
    assert refreshed.geometry_confidence == "OSM-DERIVED"

    has_path = (
        await db_session.execute(
            sa.text("SELECT path IS NOT NULL FROM routes WHERE id = :id"),
            {"id": refreshed.id},
        )
    ).scalar_one()
    assert has_path is True

    route_stops = (
        await db_session.execute(
            select(RouteStop)
            .where(RouteStop.route_id == route.id)
            .order_by(RouteStop.sequence)
        )
    ).scalars().all()
    distances = [float(rs.distance_along_route_m) for rs in route_stops]
    assert distances == [0.0, 150.0, 350.0]


@pytest.mark.asyncio
async def test_generate_route_geometry_skips_route_with_unlocated_stop(db_session):
    from scripts.generate_route_geometry import generate_route_geometry

    agency_name = f"Geometry Test Agency {uuid.uuid4()}"
    route, _ = await _make_route(
        db_session,
        agency_name=agency_name,
        short_name=f"GEO-{uuid.uuid4().hex[:6]}",
        stop_locations=["SRID=4326;POINT(73.05 33.68)", None],
    )

    provider = FakeRouteGeometryProvider({})
    stats = await generate_route_geometry(db_session, provider)

    assert stats == {"eligible": 0, "generated": 0, "failed": 0}
    assert provider.calls == []

    refreshed = (await db_session.execute(select(Route).where(Route.id == route.id))).scalar_one()
    assert refreshed.path is None
    assert refreshed.geometry_source is None
    assert refreshed.geometry_confidence is None


@pytest.mark.asyncio
async def test_generate_route_geometry_skips_route_with_single_stop(db_session):
    from scripts.generate_route_geometry import generate_route_geometry

    agency_name = f"Geometry Test Agency {uuid.uuid4()}"
    await _make_route(
        db_session,
        agency_name=agency_name,
        short_name=f"GEO-{uuid.uuid4().hex[:6]}",
        stop_locations=["SRID=4326;POINT(73.05 33.68)"],
    )

    stats = await generate_route_geometry(db_session, FakeRouteGeometryProvider({}))
    assert stats["eligible"] == 0


@pytest.mark.asyncio
async def test_generate_route_geometry_marks_unknown_on_failure(db_session):
    from scripts.generate_route_geometry import generate_route_geometry

    agency_name = f"Geometry Test Agency {uuid.uuid4()}"
    route, _ = await _make_route(
        db_session,
        agency_name=agency_name,
        short_name=f"GEO-{uuid.uuid4().hex[:6]}",
        stop_locations=["SRID=4326;POINT(73.05 33.68)", "SRID=4326;POINT(73.90 34.10)"],
    )

    # No canned response for these waypoints -> provider always raises.
    stats = await generate_route_geometry(db_session, FakeRouteGeometryProvider({}))
    assert stats == {"eligible": 1, "generated": 0, "failed": 1}

    refreshed = (await db_session.execute(select(Route).where(Route.id == route.id))).scalar_one()
    assert refreshed.path is None
    assert refreshed.geometry_source is None  # never set on a failed attempt
    assert refreshed.geometry_confidence == "UNKNOWN"


@pytest.mark.asyncio
async def test_generate_route_geometry_dry_run_writes_nothing(db_session):
    from scripts.generate_route_geometry import generate_route_geometry

    agency_name = f"Geometry Test Agency {uuid.uuid4()}"
    route, _ = await _make_route(
        db_session,
        agency_name=agency_name,
        short_name=f"GEO-{uuid.uuid4().hex[:6]}",
        stop_locations=["SRID=4326;POINT(73.05 33.68)", "SRID=4326;POINT(73.07 33.70)"],
    )

    waypoints = ((33.68, 73.05), (33.70, 73.07))
    provider = FakeRouteGeometryProvider(
        {
            waypoints: RouteGeometryResult(
                coordinates=((73.05, 33.68), (73.07, 33.70)), leg_distances_m=(500.0,)
            )
        }
    )

    stats = await generate_route_geometry(db_session, provider, dry_run=True)
    assert stats == {"eligible": 1, "generated": 1, "failed": 0}

    refreshed = (await db_session.execute(select(Route).where(Route.id == route.id))).scalar_one()
    assert refreshed.path is None
    assert refreshed.geometry_source is None
    assert refreshed.geometry_confidence is None


@pytest.mark.asyncio
async def test_generate_route_geometry_respects_limit(db_session):
    from scripts.generate_route_geometry import generate_route_geometry

    for i in range(3):
        await _make_route(
            db_session,
            agency_name=f"Geometry Limit Agency {uuid.uuid4()}",
            short_name=f"GEO-{uuid.uuid4().hex[:6]}-{i}",
            stop_locations=["SRID=4326;POINT(73.05 33.68)", "SRID=4326;POINT(73.07 33.70)"],
        )

    stats = await generate_route_geometry(db_session, FakeRouteGeometryProvider({}), limit=2)
    assert stats["eligible"] == 2


# ---------------------------------------------------------------------------
# API: GET /transit/routes/{id} and GET /transit/routes/{id}/geometry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_detail_has_null_geometry_before_generation(db_session, client):
    route, _ = await _make_route(
        db_session,
        agency_name=f"Geometry API Agency {uuid.uuid4()}",
        short_name=f"GEO-{uuid.uuid4().hex[:6]}",
        stop_locations=["SRID=4326;POINT(73.05 33.68)", "SRID=4326;POINT(73.07 33.70)"],
    )

    response = await client.get(f"/api/transit/routes/{route.id}")
    assert response.status_code == 200
    geometry = response.json()["geometry"]
    assert geometry == {
        "type": None,
        "coordinates": None,
        "geometry_source": None,
        "geometry_confidence": None,
    }


@pytest.mark.asyncio
async def test_route_geometry_endpoint_returns_generated_linestring(db_session, client):
    from scripts.generate_route_geometry import generate_route_geometry

    route, _ = await _make_route(
        db_session,
        agency_name=f"Geometry API Agency {uuid.uuid4()}",
        short_name=f"GEO-{uuid.uuid4().hex[:6]}",
        stop_locations=["SRID=4326;POINT(73.05 33.68)", "SRID=4326;POINT(73.07 33.70)"],
    )
    waypoints = ((33.68, 73.05), (33.70, 73.07))
    provider = FakeRouteGeometryProvider(
        {
            waypoints: RouteGeometryResult(
                coordinates=((73.05, 33.68), (73.06, 33.69), (73.07, 33.70)),
                leg_distances_m=(200.0, 200.0),
            )
        }
    )
    await generate_route_geometry(db_session, provider)

    response = await client.get(f"/api/transit/routes/{route.id}/geometry")
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "LineString"
    assert body["coordinates"] == [[73.05, 33.68], [73.06, 33.69], [73.07, 33.70]]
    assert body["geometry_source"] == "OSRM"
    assert body["geometry_confidence"] == "OSM-DERIVED"

    # And the embedded copy in the full route-detail response matches.
    detail_response = await client.get(f"/api/transit/routes/{route.id}")
    assert detail_response.json()["geometry"] == body


@pytest.mark.asyncio
async def test_route_geometry_endpoint_404_for_nonexistent_route(client):
    response = await client.get(f"/api/transit/routes/{uuid.uuid4()}/geometry")
    assert response.status_code == 404
