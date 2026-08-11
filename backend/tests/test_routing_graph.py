"""
Tests for `routing.graph` (`GraphNode`/`RideEdge`/`WalkEdge`/`TransitGraph`
dataclasses and the `build_graph` builder).

Follows the same real-database convention as `tests/test_transit_models.py`
and `tests/test_transit_api.py`: a real `AsyncSession` bound to the
application's own `DATABASE_URL`, nested in a transaction that is always
rolled back, so nothing here ever persists to the developer's database.
Skipped (not failed) if that database isn't reachable.
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
from db.models import Agency, Route, RouteStop, Stop  # noqa: E402
from routing.graph import (  # noqa: E402
    WALKING_RADIUS_M,
    GraphNode,
    RideEdge,
    TransitGraph,
    WalkEdge,
    build_graph,
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
    """Same pattern as tests/test_transit_models.py's fixture of the same
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


@pytest_asyncio.fixture
async def small_network(db_session):
    """One agency, one route (S1 -> S3 -> S2, deliberately out of both
    insertion and geographic order, to make ordering bugs visible), plus a
    fourth stop far enough away to be excluded from walking edges.

    Approximate distances (Islamabad-area coordinates):
    S1-S2 ~ 130m, S1-S3 ~ 250m, S2-S3 ~ 150m (all within WALKING_RADIUS_M);
    S4 is ~25km from the others (well outside it).
    """
    agency = Agency(name=f"Graph Test Agency {uuid.uuid4()}")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="G-1")
    db_session.add(route)
    await db_session.flush()

    s1 = Stop(name="S1", location="SRID=4326;POINT(73.0479 33.6844)")
    s2 = Stop(name="S2", location="SRID=4326;POINT(73.0490 33.6850)")
    s3 = Stop(name="S3", location="SRID=4326;POINT(73.0500 33.6858)")
    s4_far = Stop(name="S4-far", location="SRID=4326;POINT(73.2000 33.9000)")
    db_session.add_all([s1, s2, s3, s4_far])
    await db_session.flush()

    db_session.add_all(
        [
            RouteStop(route_id=route.id, stop_id=s1.id, sequence=1),
            RouteStop(route_id=route.id, stop_id=s3.id, sequence=2),
            RouteStop(route_id=route.id, stop_id=s2.id, sequence=3),
        ]
    )
    await db_session.flush()

    return {"agency": agency, "route": route, "stops": {"s1": s1, "s2": s2, "s3": s3, "s4_far": s4_far}}


# ---------------------------------------------------------------------------
# Dataclass sanity
# ---------------------------------------------------------------------------


def test_dataclasses_are_frozen():
    """`GraphNode`/`RideEdge`/`WalkEdge`/`TransitGraph` must all be
    immutable - the whole point of the read-only graph design."""
    for cls in (GraphNode, RideEdge, WalkEdge, TransitGraph):
        assert cls.__dataclass_params__.frozen is True


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_contains_every_stop_as_a_node(db_session, small_network):
    graph = await build_graph(db_session)
    stops = small_network["stops"]

    for key, stop in stops.items():
        assert stop.id in graph.nodes, f"{key} missing from graph.nodes"
        node = graph.nodes[stop.id]
        assert isinstance(node, GraphNode)
        assert node.name == stop.name


@pytest.mark.asyncio
async def test_node_coordinates_round_trip_through_postgis(db_session, small_network):
    graph = await build_graph(db_session)
    node = graph.nodes[small_network["stops"]["s1"].id]
    assert node.longitude == pytest.approx(73.0479, abs=1e-3)
    assert node.latitude == pytest.approx(33.6844, abs=1e-3)


# ---------------------------------------------------------------------------
# Ride edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ride_edges_follow_sequence_not_insertion_or_geography(
    db_session, small_network
):
    """Route was seeded s1(seq=1) -> s3(seq=2) -> s2(seq=3): edges must
    follow *that* order, not row-insertion order or geographic proximity."""
    graph = await build_graph(db_session)
    stops = small_network["stops"]
    route_id = small_network["route"].id

    route_edges = [e for e in graph.ride_edges if e.route_id == route_id]
    assert len(route_edges) == 2

    edges_by_sequence = sorted(route_edges, key=lambda e: e.from_sequence)
    assert edges_by_sequence[0].from_stop_id == stops["s1"].id
    assert edges_by_sequence[0].to_stop_id == stops["s3"].id
    assert edges_by_sequence[0].from_sequence == 1
    assert edges_by_sequence[0].to_sequence == 2

    assert edges_by_sequence[1].from_stop_id == stops["s3"].id
    assert edges_by_sequence[1].to_stop_id == stops["s2"].id
    assert edges_by_sequence[1].from_sequence == 2
    assert edges_by_sequence[1].to_sequence == 3


@pytest.mark.asyncio
async def test_ride_edges_are_directed_not_bidirectional(db_session, small_network):
    """A ride edge exists s1->s3 (per the route's direction of travel) but
    NOT s3->s1 - Route rows are one-directional per the confirmed design
    decision, so no reverse edge should be synthesized."""
    graph = await build_graph(db_session)
    stops = small_network["stops"]

    directed_pairs = {(e.from_stop_id, e.to_stop_id) for e in graph.ride_edges}
    assert (stops["s1"].id, stops["s3"].id) in directed_pairs
    assert (stops["s3"].id, stops["s1"].id) not in directed_pairs


@pytest.mark.asyncio
async def test_ride_edges_carry_route_and_distance_metadata(db_session, small_network):
    graph = await build_graph(db_session)
    stops = small_network["stops"]
    route = small_network["route"]

    edge = next(
        e
        for e in graph.ride_edges
        if e.from_stop_id == stops["s1"].id and e.to_stop_id == stops["s3"].id
    )
    assert edge.route_id == route.id
    assert edge.agency_id == small_network["agency"].id
    # distance_along_route_m was never set on these RouteStop rows.
    assert edge.from_distance_along_route_m is None
    assert edge.to_distance_along_route_m is None


@pytest.mark.asyncio
async def test_route_with_a_single_stop_produces_no_ride_edges(db_session):
    """A route with only one stop has no consecutive pair to form an edge
    from - must not error, must simply produce zero ride edges for it."""
    agency = Agency(name=f"Single Stop Agency {uuid.uuid4()}")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name="ONE-1")
    db_session.add(route)
    await db_session.flush()

    stop = Stop(name="Only Stop", location="SRID=4326;POINT(73.00 33.60)")
    db_session.add(stop)
    await db_session.flush()

    db_session.add(RouteStop(route_id=route.id, stop_id=stop.id, sequence=1))
    await db_session.flush()

    graph = await build_graph(db_session)
    assert stop.id in graph.nodes
    assert all(e.route_id != route.id for e in graph.ride_edges)


# ---------------------------------------------------------------------------
# Walking edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_walking_edges_connect_stops_within_radius_both_directions(
    db_session, small_network
):
    graph = await build_graph(db_session)
    stops = small_network["stops"]

    walk_pairs = {(e.from_stop_id, e.to_stop_id) for e in graph.walk_edges}
    for a, b in (("s1", "s2"), ("s1", "s3"), ("s2", "s3")):
        assert (stops[a].id, stops[b].id) in walk_pairs, f"{a}->{b} missing"
        assert (stops[b].id, stops[a].id) in walk_pairs, f"{b}->{a} missing"


@pytest.mark.asyncio
async def test_walking_edges_exclude_stops_outside_radius(db_session, small_network):
    graph = await build_graph(db_session)
    far_id = small_network["stops"]["s4_far"].id

    assert all(
        far_id not in (e.from_stop_id, e.to_stop_id) for e in graph.walk_edges
    )
    assert far_id not in graph.walk_edges_by_from


@pytest.mark.asyncio
async def test_walking_edge_distance_is_positive_and_symmetric(
    db_session, small_network
):
    graph = await build_graph(db_session)
    stops = small_network["stops"]

    forward = next(
        e
        for e in graph.walk_edges
        if e.from_stop_id == stops["s1"].id and e.to_stop_id == stops["s2"].id
    )
    backward = next(
        e
        for e in graph.walk_edges
        if e.from_stop_id == stops["s2"].id and e.to_stop_id == stops["s1"].id
    )
    assert forward.distance_m > 0
    assert forward.distance_m == pytest.approx(backward.distance_m, rel=1e-6)
    assert forward.distance_m < WALKING_RADIUS_M


@pytest.mark.asyncio
async def test_walking_edges_do_not_include_self_pairs(db_session, small_network):
    graph = await build_graph(db_session)
    assert all(e.from_stop_id != e.to_stop_id for e in graph.walk_edges)


# ---------------------------------------------------------------------------
# Adjacency indexes / overall structure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adjacency_indexes_match_edge_lists(db_session, small_network):
    graph = await build_graph(db_session)

    assert sum(len(v) for v in graph.ride_edges_by_from.values()) == len(
        graph.ride_edges
    )
    assert sum(len(v) for v in graph.walk_edges_by_from.values()) == len(
        graph.walk_edges
    )

    s1_id = small_network["stops"]["s1"].id
    assert graph.ride_edges_by_from[s1_id] == tuple(
        e for e in graph.ride_edges if e.from_stop_id == s1_id
    )
    assert graph.walk_edges_by_from[s1_id] == tuple(
        e for e in graph.walk_edges if e.from_stop_id == s1_id
    )


@pytest.mark.asyncio
async def test_graph_is_read_only(db_session, small_network):
    """`TransitGraph`'s containers must genuinely reject mutation, not just
    be conventionally-treated-as-read-only."""
    graph = await build_graph(db_session)

    with pytest.raises(AttributeError):
        graph.ride_edges.append(None)  # tuples have no .append

    with pytest.raises(TypeError):
        graph.nodes[uuid.uuid4()] = None  # MappingProxyType rejects writes

    with pytest.raises(TypeError):
        graph.ride_edges_by_from[uuid.uuid4()] = ()


@pytest.mark.asyncio
async def test_build_graph_on_empty_database_returns_empty_graph(db_session):
    """No stops/routes seeded in this test's transaction - `build_graph`
    must return a valid, empty graph rather than erroring."""
    graph = await build_graph(db_session)
    assert isinstance(graph, TransitGraph)
    assert graph.nodes == {}
    assert graph.ride_edges == ()
    assert graph.walk_edges == ()
