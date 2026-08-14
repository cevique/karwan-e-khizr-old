"""
Tests for `POST /api/transit/journeys/search`.

Follows the same real-database, rolled-back-transaction convention as
`test_transit_api.py`: a real `AsyncSession` bound to the application's
own `DATABASE_URL`, nested in a transaction that is always rolled back.
`get_transit_graph` is overridden to return a graph built from that SAME
session (so it sees the test's flushed-but-uncommitted seed data, exactly
as a graph built mid-transaction would) - not a separately-committed
graph as in `test_graph_state.py`, since this file isn't testing the
startup/rebuild lifecycle itself, just providing a graph for the search
to run against.

Kept entirely separate from the pure `routing.*` test suite
(`test_routing_search.py`, `test_routing_objectives.py`,
`test_routing_journey.py`), which needs no database at all - this file is
specifically about the HTTP/API layer built on top of that already-tested
engine.
"""

import os
import uuid
from unittest.mock import patch

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from api.graph_state import get_transit_graph
from core.config import settings
from db.models import Agency, Route, RouteStop, Stop
from db.session import get_session
from main import app
from routing.config import TRANSFER_PENALTY_S
from routing.graph import build_graph


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
    """Same pattern as test_transit_api.py's fixture of the same name: a
    real AsyncSession, nested in a transaction that's always rolled back
    on teardown, so nothing committed here persists."""
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
    """A small network deliberately engineered (via explicit
    `distance_along_route_m` values, not real geography) so `fastest` and
    `fewest_transfers` provably disagree:

    - Route A: S1 -> S2, 50m (~9s ride time)
    - Route B: S2 -> S3, 50m (~9s ride time)
    - Route C: S1 -> S3 direct, 10,000m (~1800s ride time)

    `fastest`: transfer path A+B costs ~9+9+240 (penalty) = 258s, beating
    C's ~1800s -> picks the transfer path.
    `fewest_transfers`: C has 0 transfers vs. the transfer path's 1 -> picks
    C (the direct route) despite it being far slower.

    Stop coordinates: S1/S2/S3 are all mutually >400m apart (outside
    routing.graph's WALKING_RADIUS_M), so no walking edge in the base
    graph can shortcut the intended route structure - the only way from
    S1 to S2, or S2 to S3, is via the engineered ride edges above. Tests
    additionally use a tight `max_walk_m=60` snap radius (see
    `_search_body`'s default) so the origin/destination themselves only
    ever snap to the single intended stop, not a farther one that
    happens to also be in range.

    S4/S5 are geographically isolated, deliberately orphaned (on no
    route), for the "candidates exist but no path connects them" case.
    """
    agency = Agency(name=f"Journey API Test Agency {uuid.uuid4()}")
    db_session.add(agency)
    await db_session.flush()

    route_a = Route(agency_id=agency.id, short_name="A")
    route_b = Route(agency_id=agency.id, short_name="B")
    route_c = Route(agency_id=agency.id, short_name="C")
    db_session.add_all([route_a, route_b, route_c])
    await db_session.flush()

    s1 = Stop(name="S1", location="SRID=4326;POINT(73.0479 33.6844)")
    s2 = Stop(name="S2", location="SRID=4326;POINT(73.0550 33.6900)")
    s3 = Stop(name="S3", location="SRID=4326;POINT(73.0700 33.7000)")
    s4 = Stop(name="S4 (isolated)", location="SRID=4326;POINT(74.0000 34.5000)")
    s5 = Stop(name="S5 (isolated)", location="SRID=4326;POINT(74.0200 34.5100)")
    db_session.add_all([s1, s2, s3, s4, s5])
    await db_session.flush()

    db_session.add_all(
        [
            RouteStop(
                route_id=route_a.id, stop_id=s1.id, sequence=1, distance_along_route_m=0
            ),
            RouteStop(
                route_id=route_a.id, stop_id=s2.id, sequence=2, distance_along_route_m=50
            ),
            RouteStop(
                route_id=route_b.id, stop_id=s2.id, sequence=1, distance_along_route_m=0
            ),
            RouteStop(
                route_id=route_b.id, stop_id=s3.id, sequence=2, distance_along_route_m=50
            ),
            RouteStop(
                route_id=route_c.id, stop_id=s1.id, sequence=1, distance_along_route_m=0
            ),
            RouteStop(
                route_id=route_c.id,
                stop_id=s3.id,
                sequence=2,
                distance_along_route_m=10_000,
            ),
        ]
    )
    await db_session.flush()

    return {
        "agency": agency,
        "route_a": route_a,
        "route_b": route_b,
        "route_c": route_c,
        "s1": s1,
        "s2": s2,
        "s3": s3,
        "s4": s4,
        "s5": s5,
    }


@pytest_asyncio.fixture
async def client(db_session, seeded):
    """An httpx AsyncClient wired to the real app, with `get_session`
    overridden to yield the rolled-back `db_session`, and
    `get_transit_graph` overridden to return a graph built from that SAME
    session/transaction - so it sees `seeded`'s data without needing a
    genuine cross-connection commit."""
    graph = await build_graph(db_session)

    async def override_get_session():
        yield db_session

    def override_get_transit_graph():
        return graph

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_transit_graph] = override_get_transit_graph
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_transit_graph, None)


def _search_body(
    origin=(33.6844, 73.0479),
    destination=(33.7000, 73.0700),
    objective="fastest",
    max_walk_m=60.0,
    departure_time=None,
):
    body = {
        "origin": {"latitude": origin[0], "longitude": origin[1]},
        "destination": {"latitude": destination[0], "longitude": destination[1]},
        "objective": objective,
    }
    if max_walk_m is not None:
        body["max_walk_m"] = max_walk_m
    if departure_time is not None:
        body["departure_time"] = departure_time
    return body


# ---------------------------------------------------------------------------
# Valid journeys: fastest / fewest_transfers, and that they can differ
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_fastest_journey(client, seeded):
    response = await client.post(
        "/api/transit/journeys/search", json=_search_body(objective="fastest")
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["journeys"]) == 1
    journey = body["journeys"][0]
    assert journey["objective"] == "fastest"
    assert journey["transfer_count"] == 1  # picks the A+B transfer path
    ride_legs = [leg for leg in journey["legs"] if leg["type"] == "ride"]
    assert {leg["route"]["short_name"] for leg in ride_legs} == {"A", "B"}


@pytest.mark.asyncio
async def test_valid_fewest_transfers_journey(client, seeded):
    response = await client.post(
        "/api/transit/journeys/search", json=_search_body(objective="fewest_transfers")
    )
    assert response.status_code == 200
    journey = response.json()["journeys"][0]
    assert journey["objective"] == "fewest_transfers"
    assert journey["transfer_count"] == 0  # picks the direct C route instead
    ride_legs = [leg for leg in journey["legs"] if leg["type"] == "ride"]
    assert {leg["route"]["short_name"] for leg in ride_legs} == {"C"}


@pytest.mark.asyncio
async def test_fastest_and_fewest_transfers_choose_different_journeys(client, seeded):
    fastest_response = await client.post(
        "/api/transit/journeys/search", json=_search_body(objective="fastest")
    )
    fewest_transfers_response = await client.post(
        "/api/transit/journeys/search", json=_search_body(objective="fewest_transfers")
    )

    fastest_routes = {
        leg["route"]["short_name"]
        for leg in fastest_response.json()["journeys"][0]["legs"]
        if leg["type"] == "ride"
    }
    fewest_transfers_routes = {
        leg["route"]["short_name"]
        for leg in fewest_transfers_response.json()["journeys"][0]["legs"]
        if leg["type"] == "ride"
    }
    assert fastest_routes != fewest_transfers_routes
    assert fastest_routes == {"A", "B"}
    assert fewest_transfers_routes == {"C"}


# ---------------------------------------------------------------------------
# Origin/destination snapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_origin_snapping_produces_a_leading_walk_leg(client, seeded):
    # Origin offset ~30m from S1 (not exactly on it), so the first leg has
    # a genuinely nonzero walking distance/duration.
    response = await client.post(
        "/api/transit/journeys/search",
        json=_search_body(origin=(33.68465, 73.04805)),
    )
    assert response.status_code == 200
    first_leg = response.json()["journeys"][0]["legs"][0]
    assert first_leg["type"] == "walk"
    assert first_leg["from_stop"] is None
    assert first_leg["to_stop"]["name"] == "S1"
    assert first_leg["distance_m"] > 0
    assert first_leg["duration_s"] > 0
    # from_location must be the request's own origin coordinate.
    assert first_leg["from_location"]["latitude"] == pytest.approx(33.68465, abs=1e-4)


@pytest.mark.asyncio
async def test_destination_snapping_produces_a_trailing_walk_leg(client, seeded):
    response = await client.post(
        "/api/transit/journeys/search",
        json=_search_body(destination=(33.70035, 73.07035)),
    )
    assert response.status_code == 200
    last_leg = response.json()["journeys"][0]["legs"][-1]
    assert last_leg["type"] == "walk"
    assert last_leg["to_stop"] is None
    assert last_leg["from_stop"]["name"] == "S3"
    assert last_leg["distance_m"] > 0
    assert last_leg["to_location"]["latitude"] == pytest.approx(33.70035, abs=1e-4)


# ---------------------------------------------------------------------------
# No nearby candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_nearby_origin_stops_returns_422(client, seeded):
    response = await client.post(
        "/api/transit/journeys/search",
        json=_search_body(origin=(10.0, 10.0)),  # far from every seeded stop
    )
    assert response.status_code == 422
    assert "origin" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_no_nearby_destination_stops_returns_422(client, seeded):
    response = await client.post(
        "/api/transit/journeys/search",
        json=_search_body(destination=(10.0, 10.0)),
    )
    assert response.status_code == 422
    assert "destination" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Candidates exist, no path -> 200 + empty journeys
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidates_exist_but_no_path_returns_200_with_empty_journeys(
    client, seeded
):
    response = await client.post(
        "/api/transit/journeys/search",
        json=_search_body(origin=(34.5000, 74.0000), destination=(34.5100, 74.0200)),
    )
    assert response.status_code == 200
    assert response.json() == {"journeys": []}


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_latitude_returns_422(client, seeded):
    body = _search_body()
    body["origin"]["latitude"] = 200.0
    response = await client.post("/api/transit/journeys/search", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_malformed_longitude_returns_422(client, seeded):
    body = _search_body()
    body["destination"]["longitude"] = -200.0
    response = await client.post("/api/transit/journeys/search", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_objective_returns_422(client, seeded):
    response = await client.post(
        "/api/transit/journeys/search",
        json=_search_body(objective="shortest_distance"),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_max_walk_m_returns_422(client, seeded):
    for bad_value in (-5.0, 0.0, 50_000.0):
        response = await client.post(
            "/api/transit/journeys/search", json=_search_body(max_walk_m=bad_value)
        )
        assert response.status_code == 422, f"max_walk_m={bad_value} should be rejected"


@pytest.mark.asyncio
async def test_departure_time_is_accepted_but_does_not_affect_the_result(
    client, seeded
):
    with_time = await client.post(
        "/api/transit/journeys/search",
        json=_search_body(departure_time="2026-08-14T09:00:00Z"),
    )
    without_time = await client.post(
        "/api/transit/journeys/search", json=_search_body()
    )
    assert with_time.status_code == 200
    assert with_time.json() == without_time.json()


# ---------------------------------------------------------------------------
# Graph obtained from app state, never rebuilt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_never_rebuilds_the_graph(client, seeded):
    with patch(
        "routing.graph.build_graph", side_effect=AssertionError("must not rebuild")
    ):
        response = await client.post(
            "/api/transit/journeys/search", json=_search_body()
        )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Response shape: Pydantic-only data, leg discrimination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_response_contains_only_json_compatible_data(client, seeded):
    response = await client.post("/api/transit/journeys/search", json=_search_body())
    assert response.status_code == 200
    journey = response.json()["journeys"][0]

    for leg in journey["legs"]:
        assert isinstance(leg["distance_m" if leg["type"] == "walk" else "duration_s"], (int, float))
        assert leg["type"] in ("walk", "ride")
        if leg["type"] == "ride":
            assert isinstance(leg["route"]["id"], str)
            uuid.UUID(leg["route"]["id"])  # must be a valid UUID string, not an object
            assert isinstance(leg["agency"]["name"], str)
            for stop in [leg["board_stop"], leg["alight_stop"], *leg["intermediate_stops"]]:
                assert isinstance(stop["location"]["latitude"], (int, float))


@pytest.mark.asyncio
async def test_walk_and_ride_legs_are_correctly_discriminated(client, seeded):
    response = await client.post("/api/transit/journeys/search", json=_search_body())
    journey = response.json()["journeys"][0]

    assert journey["legs"][0]["type"] == "walk"
    assert journey["legs"][-1]["type"] == "walk"
    assert all(
        leg["type"] == "ride" for leg in journey["legs"][1:-1] if "route" in leg
    )
    # Ride legs must have route/agency/board_stop/alight_stop/intermediate_stops;
    # walk legs must not have any of those fields.
    for leg in journey["legs"]:
        if leg["type"] == "ride":
            assert {"route", "agency", "board_stop", "alight_stop", "intermediate_stops"}.issubset(
                leg.keys()
            )
        else:
            assert "route" not in leg
            assert "from_location" in leg and "to_location" in leg


# ---------------------------------------------------------------------------
# Transfer count and passenger-facing duration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fastest_total_duration_includes_transfer_penalty(client, seeded):
    response = await client.post(
        "/api/transit/journeys/search", json=_search_body(objective="fastest")
    )
    journey = response.json()["journeys"][0]
    assert journey["transfer_count"] == 1

    raw_leg_duration_sum = sum(leg["duration_s"] for leg in journey["legs"])
    assert journey["total_duration_s"] == pytest.approx(
        raw_leg_duration_sum + TRANSFER_PENALTY_S
    )
    # And it must NOT equal the un-penalized raw sum on its own.
    assert journey["total_duration_s"] != pytest.approx(raw_leg_duration_sum)


@pytest.mark.asyncio
async def test_fewest_transfers_total_duration_has_no_penalty_when_zero_transfers(
    client, seeded
):
    response = await client.post(
        "/api/transit/journeys/search", json=_search_body(objective="fewest_transfers")
    )
    journey = response.json()["journeys"][0]
    assert journey["transfer_count"] == 0

    raw_leg_duration_sum = sum(leg["duration_s"] for leg in journey["legs"])
    assert journey["total_duration_s"] == pytest.approx(raw_leg_duration_sum)


# ---------------------------------------------------------------------------
# Existing endpoints remain functional
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_still_works(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_existing_transit_agencies_endpoint_still_works(client, seeded):
    response = await client.get("/api/transit/agencies")
    assert response.status_code == 200
    assert any(a["id"] == str(seeded["agency"].id) for a in response.json())


@pytest.mark.asyncio
async def test_existing_transit_routes_endpoint_still_works(client, seeded):
    response = await client.get("/api/transit/routes")
    assert response.status_code == 200
    assert len(response.json()) >= 3


@pytest.mark.asyncio
async def test_existing_transit_stops_endpoint_still_works(client, seeded):
    response = await client.get("/api/transit/stops")
    assert response.status_code == 200
    assert len(response.json()) >= 5
