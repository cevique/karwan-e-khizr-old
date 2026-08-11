"""
Tests for Step 2: walking/time-estimation providers.

Covers `routing.geo` (pure math, no DB), `routing.providers`
(`WalkingProvider`/`StraightLineWalkingProvider`), `routing.ride_time`
(`estimate_ride_time_seconds`), and the `routing.graph.build_graph`
refactor that wires them in. The pure-math/provider tests need no
database at all; the graph-integration tests follow the same real-
database, rolled-back-transaction convention as `test_routing_graph.py`
and the rest of this project's test suite.
"""

import math
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
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop  # noqa: E402
from routing.geo import Point, haversine_distance_m  # noqa: E402
from routing.graph import build_graph  # noqa: E402
from routing.providers import (  # noqa: E402
    WALKING_SPEED_KMH,
    StraightLineWalkingProvider,
    WalkEstimate,
    WalkingProvider,
    walking_duration_seconds,
)
from routing.ride_time import (  # noqa: E402
    AVERAGE_BUS_SPEED_KMH,
    estimate_ride_time_seconds,
)


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
    """Same pattern as tests/test_routing_graph.py's fixture of the same
    name: a real AsyncSession, nested in a transaction that's always rolled
    back on teardown, so nothing committed here persists."""
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


# ---------------------------------------------------------------------------
# routing.geo - pure math, no database needed
# ---------------------------------------------------------------------------


def test_haversine_distance_between_identical_points_is_zero():
    p = Point(latitude=33.6844, longitude=73.0479)
    assert haversine_distance_m(p, p) == pytest.approx(0.0, abs=1e-6)


def test_haversine_distance_is_symmetric():
    a = Point(latitude=33.6844, longitude=73.0479)
    b = Point(latitude=33.6850, longitude=73.0490)
    assert haversine_distance_m(a, b) == pytest.approx(
        haversine_distance_m(b, a), rel=1e-9
    )


def test_haversine_distance_matches_known_earth_geometry():
    """Two points exactly 1 degree of latitude apart (same longitude) are a
    textbook-verifiable distance: Earth's mean circumference (2*pi*R, with
    R = 6,371,000m, the same mean radius this module uses) / 360 =~
    111.19 km - independent of which haversine implementation is used,
    since it follows directly from the sphere's geometry."""
    a = Point(latitude=33.0, longitude=73.0)
    b = Point(latitude=34.0, longitude=73.0)
    expected_km = (2 * math.pi * 6_371_000.0 / 360.0) / 1000.0
    assert haversine_distance_m(a, b) / 1000.0 == pytest.approx(expected_km, rel=1e-6)


def test_haversine_distance_small_scale_matches_expected_order_of_magnitude():
    """Two points ~0.0001 deg apart in latitude (~11.1m at the equator,
    slightly less at ~33 deg N) should be a handful of meters apart, not
    kilometers or millimeters - guards against a degrees/radians mixup."""
    a = Point(latitude=33.6844, longitude=73.0479)
    b = Point(latitude=33.6845, longitude=73.0479)
    distance_m = haversine_distance_m(a, b)
    assert 5.0 < distance_m < 15.0


# ---------------------------------------------------------------------------
# routing.providers - pure math, no database needed
# ---------------------------------------------------------------------------


def test_walking_duration_seconds_known_case():
    # 900m at 4.5 km/h (1.25 m/s) = 720s exactly.
    assert walking_duration_seconds(900.0, speed_kmh=4.5) == pytest.approx(720.0)


def test_walking_duration_seconds_uses_default_speed_constant():
    distance_m = 450.0
    expected = distance_m / (WALKING_SPEED_KMH * 1000.0 / 3600.0)
    assert walking_duration_seconds(distance_m) == pytest.approx(expected)


def test_walking_duration_seconds_rejects_non_positive_speed():
    with pytest.raises(ValueError):
        walking_duration_seconds(100.0, speed_kmh=0)
    with pytest.raises(ValueError):
        walking_duration_seconds(100.0, speed_kmh=-1)


@pytest.mark.asyncio
async def test_straight_line_walking_provider_known_distance_and_duration():
    provider = StraightLineWalkingProvider()
    a = Point(latitude=33.6844, longitude=73.0479)
    b = Point(latitude=33.6850, longitude=73.0490)

    estimate = await provider.estimate_walk(a, b)

    assert isinstance(estimate, WalkEstimate)
    expected_distance = haversine_distance_m(a, b)
    assert estimate.distance_m == pytest.approx(expected_distance)
    assert estimate.duration_s == pytest.approx(
        walking_duration_seconds(expected_distance)
    )


@pytest.mark.asyncio
async def test_straight_line_walking_provider_is_symmetric():
    provider = StraightLineWalkingProvider()
    a = Point(latitude=33.6844, longitude=73.0479)
    b = Point(latitude=33.7100, longitude=73.0700)

    forward = await provider.estimate_walk(a, b)
    backward = await provider.estimate_walk(b, a)

    assert forward.distance_m == pytest.approx(backward.distance_m)
    assert forward.duration_s == pytest.approx(backward.duration_s)


@pytest.mark.asyncio
async def test_straight_line_walking_provider_honors_custom_speed():
    a = Point(latitude=33.6844, longitude=73.0479)
    b = Point(latitude=33.6850, longitude=73.0490)

    slow_provider = StraightLineWalkingProvider(speed_kmh=1.0)
    fast_provider = StraightLineWalkingProvider(speed_kmh=9.0)

    slow_estimate = await slow_provider.estimate_walk(a, b)
    fast_estimate = await fast_provider.estimate_walk(a, b)

    # Same distance either way; a provider configured 9x faster should take
    # 1/9th the time.
    assert slow_estimate.distance_m == pytest.approx(fast_estimate.distance_m)
    assert slow_estimate.duration_s == pytest.approx(
        fast_estimate.duration_s * 9, rel=1e-6
    )


def test_straight_line_walking_provider_satisfies_the_protocol():
    """`StraightLineWalkingProvider` must structurally satisfy
    `WalkingProvider` - the whole point of defining it as a `Protocol`."""
    assert isinstance(StraightLineWalkingProvider(), WalkingProvider)


class _FakeWalkingProvider:
    """A minimal second `WalkingProvider` implementation, proving the
    interface is genuinely substitutable and not accidentally coupled to
    `StraightLineWalkingProvider`'s internals."""

    def __init__(self, distance_m: float, duration_s: float) -> None:
        self._distance_m = distance_m
        self._duration_s = duration_s

    async def estimate_walk(self, origin: Point, destination: Point) -> WalkEstimate:
        return WalkEstimate(distance_m=self._distance_m, duration_s=self._duration_s)


def test_fake_walking_provider_also_satisfies_the_protocol():
    assert isinstance(_FakeWalkingProvider(1.0, 2.0), WalkingProvider)


@pytest.mark.asyncio
async def test_fake_walking_provider_is_a_drop_in_substitute():
    provider: WalkingProvider = _FakeWalkingProvider(distance_m=1234.0, duration_s=999.0)
    estimate = await provider.estimate_walk(
        Point(latitude=0.0, longitude=0.0), Point(latitude=1.0, longitude=1.0)
    )
    assert estimate == WalkEstimate(distance_m=1234.0, duration_s=999.0)


# ---------------------------------------------------------------------------
# routing.ride_time - pure math, no database needed (GraphNode is a plain
# dataclass, so hand-building one here needs no session/DB access)
# ---------------------------------------------------------------------------


def _node(latitude: float, longitude: float):
    from routing.graph import GraphNode

    return GraphNode(stop_id=uuid.uuid4(), name="test", latitude=latitude, longitude=longitude)


def test_estimate_ride_time_uses_distance_along_route_when_available():
    from_node = _node(33.6844, 73.0479)
    to_node = _node(33.7100, 73.0700)  # far away - must NOT be used here

    duration_s = estimate_ride_time_seconds(
        from_distance_along_route_m=100.0,
        to_distance_along_route_m=1000.0,
        from_node=from_node,
        to_node=to_node,
        speed_kmh=18.0,
    )
    expected = (1000.0 - 100.0) / (18.0 * 1000.0 / 3600.0)
    assert duration_s == pytest.approx(expected)


def test_estimate_ride_time_falls_back_to_haversine_when_distances_missing():
    from_node = _node(33.6844, 73.0479)
    to_node = _node(33.6850, 73.0490)

    duration_s = estimate_ride_time_seconds(
        from_distance_along_route_m=None,
        to_distance_along_route_m=None,
        from_node=from_node,
        to_node=to_node,
        speed_kmh=18.0,
    )
    expected_distance = haversine_distance_m(
        Point(from_node.latitude, from_node.longitude),
        Point(to_node.latitude, to_node.longitude),
    )
    expected = expected_distance / (18.0 * 1000.0 / 3600.0)
    assert duration_s == pytest.approx(expected)


def test_estimate_ride_time_falls_back_when_only_one_distance_present():
    from_node = _node(33.6844, 73.0479)
    to_node = _node(33.6850, 73.0490)

    duration_s = estimate_ride_time_seconds(
        from_distance_along_route_m=100.0,
        to_distance_along_route_m=None,
        from_node=from_node,
        to_node=to_node,
    )
    expected_distance = haversine_distance_m(
        Point(from_node.latitude, from_node.longitude),
        Point(to_node.latitude, to_node.longitude),
    )
    expected = expected_distance / (AVERAGE_BUS_SPEED_KMH * 1000.0 / 3600.0)
    assert duration_s == pytest.approx(expected)


def test_estimate_ride_time_falls_back_when_distances_are_non_monotonic():
    """`to` <= `from` is treated as unusable data, not a negative-time
    segment - falls back to the haversine estimate instead."""
    from_node = _node(33.6844, 73.0479)
    to_node = _node(33.6850, 73.0490)

    duration_s = estimate_ride_time_seconds(
        from_distance_along_route_m=500.0,
        to_distance_along_route_m=500.0,  # equal, not increasing
        from_node=from_node,
        to_node=to_node,
    )
    expected_distance = haversine_distance_m(
        Point(from_node.latitude, from_node.longitude),
        Point(to_node.latitude, to_node.longitude),
    )
    expected = expected_distance / (AVERAGE_BUS_SPEED_KMH * 1000.0 / 3600.0)
    assert duration_s == pytest.approx(expected)

    duration_s_reversed = estimate_ride_time_seconds(
        from_distance_along_route_m=800.0,
        to_distance_along_route_m=200.0,  # decreasing
        from_node=from_node,
        to_node=to_node,
    )
    assert duration_s_reversed == pytest.approx(expected)


def test_estimate_ride_time_uses_default_bus_speed_constant():
    from_node = _node(33.6844, 73.0479)
    to_node = _node(33.6850, 73.0490)

    duration_s = estimate_ride_time_seconds(
        from_distance_along_route_m=None,
        to_distance_along_route_m=None,
        from_node=from_node,
        to_node=to_node,
    )
    expected_distance = haversine_distance_m(
        Point(from_node.latitude, from_node.longitude),
        Point(to_node.latitude, to_node.longitude),
    )
    expected = expected_distance / (AVERAGE_BUS_SPEED_KMH * 1000.0 / 3600.0)
    assert duration_s == pytest.approx(expected)


def test_estimate_ride_time_rejects_non_positive_speed():
    from_node = _node(0.0, 0.0)
    to_node = _node(1.0, 1.0)
    with pytest.raises(ValueError):
        estimate_ride_time_seconds(None, None, from_node, to_node, speed_kmh=0)


# ---------------------------------------------------------------------------
# routing.graph.build_graph integration - real PostgreSQL/PostGIS
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def small_network(db_session):
    """One agency, one route (S1 -> S2, no distance_along_route_m set, so
    ride-time estimation exercises the haversine fallback), plus a second,
    isolated pair of stops with no route between them (S3/S4) purely to
    exercise walking-edge weighting independent of any ride edge."""
    agency = Agency(name=f"Providers Test Agency {uuid.uuid4()}")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="P-1")
    db_session.add(route)
    await db_session.flush()

    s1 = Stop(name="S1", location="SRID=4326;POINT(73.0479 33.6844)")
    s2 = Stop(name="S2", location="SRID=4326;POINT(73.0490 33.6850)")  # ~130m from s1
    db_session.add_all([s1, s2])
    await db_session.flush()

    db_session.add_all(
        [
            RouteStop(route_id=route.id, stop_id=s1.id, sequence=1),
            RouteStop(route_id=route.id, stop_id=s2.id, sequence=2),
        ]
    )
    await db_session.flush()

    return {"agency": agency, "route": route, "s1": s1, "s2": s2}


@pytest.mark.asyncio
async def test_build_graph_ride_edges_have_positive_duration_by_default(
    db_session, small_network
):
    graph = await build_graph(db_session)
    edge = next(
        e for e in graph.ride_edges if e.from_stop_id == small_network["s1"].id
    )
    assert edge.duration_s > 0


@pytest.mark.asyncio
async def test_build_graph_walk_edges_use_default_walking_provider(
    db_session, small_network
):
    graph = await build_graph(db_session)
    s1, s2 = small_network["s1"], small_network["s2"]

    edge = next(
        e for e in graph.walk_edges if e.from_stop_id == s1.id and e.to_stop_id == s2.id
    )
    expected_distance = haversine_distance_m(
        Point(latitude=33.6844, longitude=73.0479),
        Point(latitude=33.6850, longitude=73.0490),
    )
    assert edge.distance_m == pytest.approx(expected_distance, rel=1e-3)
    assert edge.duration_s == pytest.approx(
        walking_duration_seconds(edge.distance_m), rel=1e-6
    )


@pytest.mark.asyncio
async def test_build_graph_accepts_a_substitute_walking_provider(
    db_session, small_network
):
    """The core substitutability requirement: swapping the provider must
    change the graph's walk-edge weights, proving `build_graph` genuinely
    calls the injected provider rather than always using its own
    PostGIS-measured distance."""
    fake_provider = _FakeWalkingProvider(distance_m=4242.0, duration_s=1234.0)
    graph = await build_graph(db_session, walking_provider=fake_provider)
    s1, s2 = small_network["s1"], small_network["s2"]

    edge = next(
        e for e in graph.walk_edges if e.from_stop_id == s1.id and e.to_stop_id == s2.id
    )
    assert edge.distance_m == 4242.0
    assert edge.duration_s == 1234.0


@pytest.mark.asyncio
async def test_build_graph_accepts_a_substitute_ride_time_estimator(
    db_session, small_network
):
    def fixed_ride_time(from_dist, to_dist, from_node, to_node) -> float:
        return 777.0

    graph = await build_graph(db_session, ride_time_estimator=fixed_ride_time)
    edge = next(
        e for e in graph.ride_edges if e.from_stop_id == small_network["s1"].id
    )
    assert edge.duration_s == 777.0


@pytest.mark.asyncio
async def test_build_graph_default_and_custom_providers_produce_different_results(
    db_session, small_network
):
    """Sanity check that the two providers used above genuinely disagree -
    guards against a test bug where the "substitute" happens to match the
    default and the substitution silently isn't being exercised."""
    default_graph = await build_graph(db_session)
    fake_graph = await build_graph(
        db_session, walking_provider=_FakeWalkingProvider(1.0, 2.0)
    )
    s1, s2 = small_network["s1"], small_network["s2"]

    default_edge = next(
        e
        for e in default_graph.walk_edges
        if e.from_stop_id == s1.id and e.to_stop_id == s2.id
    )
    fake_edge = next(
        e
        for e in fake_graph.walk_edges
        if e.from_stop_id == s1.id and e.to_stop_id == s2.id
    )
    assert default_edge.distance_m != fake_edge.distance_m
    assert not math.isclose(default_edge.duration_s, fake_edge.duration_s)
