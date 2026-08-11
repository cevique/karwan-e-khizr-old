"""
Tests for `routing.snapping` (origin/destination-to-stop snapping).

Follows the same real-database, rolled-back-transaction convention as
`test_routing_graph.py` and `test_routing_providers.py`: a real
`AsyncSession` bound to the application's own `DATABASE_URL`, nested in a
transaction that is always rolled back, so nothing here ever persists to
the developer's database. Skipped (not failed) if that database isn't
reachable.
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
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import settings  # noqa: E402
from db.models import Stop  # noqa: E402
from routing.geo import Point  # noqa: E402
from routing.providers import WalkEstimate, WalkingProvider  # noqa: E402
from routing.snapping import (  # noqa: E402
    DEFAULT_MAX_WALK_M,
    DestinationConnection,
    OriginConnection,
    SnapCandidate,
    find_nearby_stops,
    snap_destination,
    snap_origin,
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
    """Same pattern as the rest of the routing test suite: a real
    AsyncSession, nested in a transaction that's always rolled back on
    teardown, so nothing committed here persists."""
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


class _FakeWalkingProvider:
    """A `WalkingProvider` test double returning a fixed estimate
    regardless of input, proving `find_nearby_stops`/`snap_origin`/
    `snap_destination` genuinely use the injected provider rather than
    always deriving distance/duration from PostGIS."""

    def __init__(self, distance_m: float, duration_s: float) -> None:
        self._distance_m = distance_m
        self._duration_s = duration_s

    async def estimate_walk(self, origin: Point, destination: Point) -> WalkEstimate:
        return WalkEstimate(distance_m=self._distance_m, duration_s=self._duration_s)


@pytest_asyncio.fixture
async def nearby_stops(db_session):
    """Three stops at increasing distance from a fixed query point, plus
    one stop far outside DEFAULT_MAX_WALK_M.

    Query point: (33.6844, 73.0479). Approximate distances: near1 ~130m,
    near2 ~250m, near3 ~500m (still within the 800m default), far ~25km
    (well outside any radius used in these tests).
    """
    near1 = Stop(name="Near1", location="SRID=4326;POINT(73.0490 33.6850)")
    near2 = Stop(name="Near2", location="SRID=4326;POINT(73.0500 33.6858)")
    near3 = Stop(name="Near3", location="SRID=4326;POINT(73.0520 33.6880)")
    far = Stop(name="Far", location="SRID=4326;POINT(73.2000 33.9000)")
    db_session.add_all([near1, near2, near3, far])
    await db_session.flush()

    return {
        "query_point": Point(latitude=33.6844, longitude=73.0479),
        "near1": near1,
        "near2": near2,
        "near3": near3,
        "far": far,
    }


# ---------------------------------------------------------------------------
# find_nearby_stops: ordering, radius exclusion, empty case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidates_ordered_nearest_first(db_session, nearby_stops):
    candidates = await find_nearby_stops(db_session, nearby_stops["query_point"])

    ids_in_order = [c.stop_id for c in candidates]
    assert ids_in_order == [
        nearby_stops["near1"].id,
        nearby_stops["near2"].id,
        nearby_stops["near3"].id,
    ]
    # Distances must themselves be non-decreasing, not just id order by
    # coincidence.
    distances = [c.distance_m for c in candidates]
    assert distances == sorted(distances)


@pytest.mark.asyncio
async def test_candidates_exclude_stops_outside_default_radius(
    db_session, nearby_stops
):
    candidates = await find_nearby_stops(db_session, nearby_stops["query_point"])
    assert nearby_stops["far"].id not in [c.stop_id for c in candidates]


@pytest.mark.asyncio
async def test_max_walk_m_is_respected_and_configurable(db_session, nearby_stops):
    point = nearby_stops["query_point"]

    tight = await find_nearby_stops(db_session, point, max_walk_m=150.0)
    assert [c.stop_id for c in tight] == [nearby_stops["near1"].id]

    wide = await find_nearby_stops(db_session, point, max_walk_m=600.0)
    assert set(c.stop_id for c in wide) == {
        nearby_stops["near1"].id,
        nearby_stops["near2"].id,
        nearby_stops["near3"].id,
    }

    very_tight = await find_nearby_stops(db_session, point, max_walk_m=10.0)
    assert very_tight == ()


@pytest.mark.asyncio
async def test_default_max_walk_m_constant_is_used_when_not_specified(
    db_session, nearby_stops
):
    """Sanity check that the DEFAULT_MAX_WALK_M constant (not some other
    hardcoded value) is what's actually applied when the caller doesn't
    override it."""
    point = nearby_stops["query_point"]
    default_result = await find_nearby_stops(db_session, point)
    explicit_result = await find_nearby_stops(
        db_session, point, max_walk_m=DEFAULT_MAX_WALK_M
    )
    assert [c.stop_id for c in default_result] == [c.stop_id for c in explicit_result]


@pytest.mark.asyncio
async def test_no_candidates_returns_empty_tuple_not_an_exception(db_session):
    """An empty stops table (no seeding at all in this test) must produce a
    clean empty result, never raise."""
    point = Point(latitude=33.6844, longitude=73.0479)
    result = await find_nearby_stops(db_session, point)
    assert result == ()
    assert isinstance(result, tuple)


@pytest.mark.asyncio
async def test_no_candidates_when_only_far_stops_seeded(db_session, nearby_stops):
    """Query point far from every seeded stop -> empty, not an error."""
    remote_point = Point(latitude=-33.8688, longitude=151.2093)  # Sydney
    result = await find_nearby_stops(db_session, remote_point, max_walk_m=1000.0)
    assert result == ()


@pytest.mark.asyncio
async def test_candidates_capped_at_max_snap_candidates(
    db_session, nearby_stops, monkeypatch
):
    """With the internal cap lowered to 2, only the nearest 2 of the 3
    in-radius stops should come back."""
    import routing.snapping as snapping_module

    monkeypatch.setattr(snapping_module, "MAX_SNAP_CANDIDATES", 2)

    candidates = await find_nearby_stops(db_session, nearby_stops["query_point"])
    assert len(candidates) == 2
    assert [c.stop_id for c in candidates] == [
        nearby_stops["near1"].id,
        nearby_stops["near2"].id,
    ]


# ---------------------------------------------------------------------------
# snap_origin / snap_destination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snap_origin_produces_correctly_directed_connections(
    db_session, nearby_stops
):
    connections = await snap_origin(db_session, nearby_stops["query_point"])

    assert len(connections) == 3
    assert all(isinstance(c, OriginConnection) for c in connections)
    assert [c.to_stop_id for c in connections] == [
        nearby_stops["near1"].id,
        nearby_stops["near2"].id,
        nearby_stops["near3"].id,
    ]
    for c in connections:
        assert c.distance_m > 0
        assert c.duration_s > 0


@pytest.mark.asyncio
async def test_snap_destination_produces_correctly_directed_connections(
    db_session, nearby_stops
):
    connections = await snap_destination(db_session, nearby_stops["query_point"])

    assert len(connections) == 3
    assert all(isinstance(c, DestinationConnection) for c in connections)
    assert [c.from_stop_id for c in connections] == [
        nearby_stops["near1"].id,
        nearby_stops["near2"].id,
        nearby_stops["near3"].id,
    ]
    for c in connections:
        assert c.distance_m > 0
        assert c.duration_s > 0


@pytest.mark.asyncio
async def test_snap_origin_and_snap_destination_agree_on_weights(
    db_session, nearby_stops
):
    """For the same point and the same stop, an OriginConnection and a
    DestinationConnection should carry identical distance/duration - the
    only difference between them is which end is the virtual point."""
    origin_connections = await snap_origin(db_session, nearby_stops["query_point"])
    destination_connections = await snap_destination(
        db_session, nearby_stops["query_point"]
    )

    origin_by_stop = {c.to_stop_id: c for c in origin_connections}
    destination_by_stop = {c.from_stop_id: c for c in destination_connections}

    assert set(origin_by_stop) == set(destination_by_stop)
    for stop_id in origin_by_stop:
        assert origin_by_stop[stop_id].distance_m == pytest.approx(
            destination_by_stop[stop_id].distance_m
        )
        assert origin_by_stop[stop_id].duration_s == pytest.approx(
            destination_by_stop[stop_id].duration_s
        )


@pytest.mark.asyncio
async def test_snap_origin_empty_when_nothing_nearby(db_session):
    result = await snap_origin(
        db_session, Point(latitude=33.6844, longitude=73.0479)
    )
    assert result == ()


@pytest.mark.asyncio
async def test_snap_destination_empty_when_nothing_nearby(db_session):
    result = await snap_destination(
        db_session, Point(latitude=33.6844, longitude=73.0479)
    )
    assert result == ()


# ---------------------------------------------------------------------------
# Provider substitution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_nearby_stops_uses_injected_walking_provider(
    db_session, nearby_stops
):
    fake_provider = _FakeWalkingProvider(distance_m=4321.0, duration_s=999.0)
    candidates = await find_nearby_stops(
        db_session, nearby_stops["query_point"], walking_provider=fake_provider
    )

    assert len(candidates) == 3
    assert all(c.distance_m == 4321.0 for c in candidates)
    assert all(c.duration_s == 999.0 for c in candidates)


@pytest.mark.asyncio
async def test_snap_origin_uses_injected_walking_provider(db_session, nearby_stops):
    fake_provider = _FakeWalkingProvider(distance_m=111.0, duration_s=22.0)
    connections = await snap_origin(
        db_session, nearby_stops["query_point"], walking_provider=fake_provider
    )
    assert all(c.distance_m == 111.0 and c.duration_s == 22.0 for c in connections)


@pytest.mark.asyncio
async def test_snap_destination_uses_injected_walking_provider(
    db_session, nearby_stops
):
    fake_provider = _FakeWalkingProvider(distance_m=111.0, duration_s=22.0)
    connections = await snap_destination(
        db_session, nearby_stops["query_point"], walking_provider=fake_provider
    )
    assert all(c.distance_m == 111.0 and c.duration_s == 22.0 for c in connections)


@pytest.mark.asyncio
async def test_default_and_substitute_provider_produce_different_results(
    db_session, nearby_stops
):
    """Guards against a test bug where the "substitute" happens to match
    the default and the substitution silently isn't being exercised."""
    default_candidates = await find_nearby_stops(
        db_session, nearby_stops["query_point"]
    )
    fake_candidates = await find_nearby_stops(
        db_session,
        nearby_stops["query_point"],
        walking_provider=_FakeWalkingProvider(1.0, 2.0),
    )

    default_by_stop = {c.stop_id: c for c in default_candidates}
    fake_by_stop = {c.stop_id: c for c in fake_candidates}

    for stop_id in default_by_stop:
        assert default_by_stop[stop_id].distance_m != fake_by_stop[stop_id].distance_m


def test_fake_walking_provider_satisfies_the_protocol():
    assert isinstance(_FakeWalkingProvider(1.0, 2.0), WalkingProvider)


# ---------------------------------------------------------------------------
# Dataclass sanity
# ---------------------------------------------------------------------------


def test_connection_and_candidate_dataclasses_are_frozen():
    for cls in (SnapCandidate, OriginConnection, DestinationConnection):
        assert cls.__dataclass_params__.frozen is True
