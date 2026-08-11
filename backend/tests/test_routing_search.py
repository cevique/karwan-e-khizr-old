"""
Tests for `routing.search` (Dijkstra shortest-path search, "fastest"
objective).

Unlike the rest of the routing test suite, these are pure, database-free
unit tests: `routing.search` has no `async`, no SQLAlchemy, and no
FastAPI dependency by design (this step's explicit requirement), so its
tests build small `TransitGraph`/`OriginConnection`/`DestinationConnection`
instances entirely by hand - exactly the "small hand-constructed graphs
where the expected shortest path can be calculated manually" this step
asks for - and never touch a database session or skip for one being
unreachable.
"""

import uuid
from types import MappingProxyType

import pytest

from routing.graph import GraphNode, RideEdge, TransitGraph, WalkEdge
from routing.search import (
    DESTINATION,
    ORIGIN,
    TRANSFER_PENALTY_S,
    SearchResult,
    find_shortest_path,
)
from routing.snapping import DestinationConnection, OriginConnection

AGENCY_ID = uuid.uuid4()


def _node(stop_id: uuid.UUID, name: str) -> GraphNode:
    return GraphNode(stop_id=stop_id, name=name, latitude=0.0, longitude=0.0)


def _ride_edge(
    route_id: uuid.UUID,
    from_stop_id: uuid.UUID,
    to_stop_id: uuid.UUID,
    duration_s: float,
    from_sequence: int = 1,
    to_sequence: int = 2,
) -> RideEdge:
    return RideEdge(
        route_id=route_id,
        agency_id=AGENCY_ID,
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        from_sequence=from_sequence,
        to_sequence=to_sequence,
        from_distance_along_route_m=None,
        to_distance_along_route_m=None,
        duration_s=duration_s,
    )


def _walk_edge(
    from_stop_id: uuid.UUID, to_stop_id: uuid.UUID, duration_s: float
) -> WalkEdge:
    return WalkEdge(
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        distance_m=duration_s * 1.25,  # arbitrary, unused by the search
        duration_s=duration_s,
    )


def _build_graph(
    stop_ids: list[uuid.UUID],
    ride_edges: tuple[RideEdge, ...] = (),
    walk_edges: tuple[WalkEdge, ...] = (),
) -> TransitGraph:
    nodes = MappingProxyType(
        {sid: _node(sid, f"stop-{i}") for i, sid in enumerate(stop_ids)}
    )

    def _group(edges, attr):
        grouped: dict[uuid.UUID, list] = {}
        for e in edges:
            grouped.setdefault(getattr(e, attr), []).append(e)
        return MappingProxyType({k: tuple(v) for k, v in grouped.items()})

    return TransitGraph(
        nodes=nodes,
        ride_edges=ride_edges,
        walk_edges=walk_edges,
        ride_edges_by_from=_group(ride_edges, "from_stop_id"),
        walk_edges_by_from=_group(walk_edges, "from_stop_id"),
    )


def _origin_at(
    stop_id: uuid.UUID, duration_s: float = 0.0
) -> tuple[OriginConnection, ...]:
    return (
        OriginConnection(
            to_stop_id=stop_id, distance_m=duration_s, duration_s=duration_s
        ),
    )


def _destination_at(
    stop_id: uuid.UUID, duration_s: float = 0.0
) -> tuple[DestinationConnection, ...]:
    return (
        DestinationConnection(
            from_stop_id=stop_id, distance_m=duration_s, duration_s=duration_s
        ),
    )


# ---------------------------------------------------------------------------
# Fastest path selection
# ---------------------------------------------------------------------------


def test_picks_the_lower_total_duration_of_two_single_route_alternatives():
    """S1 -> S3 direct (150s) vs S1 -> S2 -> S3 (80 + 80 = 160s), all on
    the same route (so no transfer penalty applies to either) - the
    direct 150s edge must win."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    direct = _ride_edge(route, s1, s3, duration_s=150.0)
    hop1 = _ride_edge(route, s1, s2, duration_s=80.0, to_sequence=2)
    hop2 = _ride_edge(route, s2, s3, duration_s=80.0, from_sequence=2, to_sequence=3)

    graph = _build_graph([s1, s2, s3], ride_edges=(direct, hop1, hop2))
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s3))

    assert result is not None
    assert result.total_duration_s == pytest.approx(150.0)
    assert direct in result.edges
    assert hop1 not in result.edges
    assert hop2 not in result.edges


def test_prefers_shorter_path_even_with_more_hops():
    """Sanity check the other direction: if the multi-hop path is
    genuinely faster, it must be chosen over a slower direct edge."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    slow_direct = _ride_edge(route, s1, s3, duration_s=500.0)
    fast_hop1 = _ride_edge(route, s1, s2, duration_s=10.0, to_sequence=2)
    fast_hop2 = _ride_edge(
        route, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3
    )

    graph = _build_graph([s1, s2, s3], ride_edges=(slow_direct, fast_hop1, fast_hop2))
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s3))

    assert result is not None
    assert result.total_duration_s == pytest.approx(20.0)
    assert fast_hop1 in result.edges and fast_hop2 in result.edges


# ---------------------------------------------------------------------------
# Walking
# ---------------------------------------------------------------------------


def test_prefers_a_faster_walking_edge_over_a_slower_ride_edge():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    slow_ride = _ride_edge(route, s1, s2, duration_s=300.0)
    fast_walk = _walk_edge(s1, s2, duration_s=100.0)

    graph = _build_graph([s1, s2], ride_edges=(slow_ride,), walk_edges=(fast_walk,))
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s2))

    assert result is not None
    assert result.total_duration_s == pytest.approx(100.0)
    assert fast_walk in result.edges
    assert slow_ride not in result.edges


def test_uses_ride_edge_when_it_is_faster_than_walking():
    """The complementary case - confirms walking isn't unconditionally
    preferred, only when it's genuinely cheaper."""
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    fast_ride = _ride_edge(route, s1, s2, duration_s=50.0)
    slow_walk = _walk_edge(s1, s2, duration_s=400.0)

    graph = _build_graph([s1, s2], ride_edges=(fast_ride,), walk_edges=(slow_walk,))
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s2))

    assert result is not None
    assert result.total_duration_s == pytest.approx(50.0)
    assert fast_ride in result.edges


# ---------------------------------------------------------------------------
# Origin/destination synthetic connections
# ---------------------------------------------------------------------------


def test_result_starts_with_origin_connection_and_ends_with_destination_connection():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride_edge(route, s1, s2, duration_s=60.0)

    graph = _build_graph([s1, s2], ride_edges=(ride,))
    origin_conns = _origin_at(s1, duration_s=25.0)
    dest_conns = _destination_at(s2, duration_s=15.0)

    result = find_shortest_path(graph, origin_conns, dest_conns)

    assert result is not None
    assert isinstance(result.edges[0], OriginConnection)
    assert result.edges[0] is origin_conns[0]
    assert isinstance(result.edges[-1], DestinationConnection)
    assert result.edges[-1] is dest_conns[0]
    assert result.total_duration_s == pytest.approx(25.0 + 60.0 + 15.0)


def test_picks_the_best_of_multiple_origin_and_destination_candidates():
    """Two candidate boarding stops, two candidate alighting stops - the
    search must pick the globally cheapest combination, not just the
    nearest origin candidate or nearest destination candidate in
    isolation."""
    s1_near, s1_far, s2_near, s2_far = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    route = uuid.uuid4()

    # The "near" origin candidate connects to a slow ride; the "far" origin
    # candidate (longer walk) connects to a much faster ride, making it the
    # better overall choice despite the longer initial walk.
    ride_from_near = _ride_edge(route, s1_near, s2_near, duration_s=500.0)
    ride_from_far = _ride_edge(route, s1_far, s2_far, duration_s=10.0, to_sequence=2)

    graph = _build_graph(
        [s1_near, s1_far, s2_near, s2_far],
        ride_edges=(ride_from_near, ride_from_far),
    )
    origin_conns = (
        OriginConnection(to_stop_id=s1_near, distance_m=10, duration_s=10.0),
        OriginConnection(to_stop_id=s1_far, distance_m=200, duration_s=200.0),
    )
    dest_conns = (
        DestinationConnection(from_stop_id=s2_near, distance_m=10, duration_s=10.0),
        DestinationConnection(from_stop_id=s2_far, distance_m=10, duration_s=10.0),
    )

    result = find_shortest_path(graph, origin_conns, dest_conns)

    assert result is not None
    # far-origin route: 200 + 10 + 10 = 220; near-origin route: 10 + 500 + 10 = 520
    assert result.total_duration_s == pytest.approx(220.0)
    assert ride_from_far in result.edges
    assert ride_from_near not in result.edges


# ---------------------------------------------------------------------------
# Transfer penalty
# ---------------------------------------------------------------------------


def test_transfer_penalty_can_make_a_single_route_path_win():
    """S1->S2 (route A, 50s) -> S3 (route B, 50s) = 100s raw + a transfer;
    vs S1->S3 direct on route C, single route, 130s raw. With
    TRANSFER_PENALTY_S added, the transfer path's real cost exceeds the
    direct path's, so the direct (transfer-free) path must be chosen even
    though it has a higher raw ride time."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b, route_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    leg_a = _ride_edge(route_a, s1, s2, duration_s=50.0, to_sequence=2)
    leg_b = _ride_edge(route_b, s2, s3, duration_s=50.0, from_sequence=2, to_sequence=3)
    direct = _ride_edge(route_c, s1, s3, duration_s=130.0)

    assert 50.0 + 50.0 + TRANSFER_PENALTY_S > 130.0, "test assumption sanity check"

    graph = _build_graph([s1, s2, s3], ride_edges=(leg_a, leg_b, direct))
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s3))

    assert result is not None
    assert result.total_duration_s == pytest.approx(130.0)
    assert direct in result.edges


def test_transfer_penalty_is_applied_when_the_transfer_path_still_wins():
    """Same shape as above, but the transfer path's raw time is short
    enough that even with the penalty added, it's still cheaper than the
    single-route alternative - confirms the penalty is genuinely *added*
    to the cost (and still lets a transfer win when it's worth it), not a
    hard rule that always avoids transfers."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b, route_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    leg_a = _ride_edge(route_a, s1, s2, duration_s=10.0, to_sequence=2)
    leg_b = _ride_edge(route_b, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)
    direct = _ride_edge(route_c, s1, s3, duration_s=10_000.0)

    graph = _build_graph([s1, s2, s3], ride_edges=(leg_a, leg_b, direct))
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s3))

    assert result is not None
    assert result.total_duration_s == pytest.approx(10.0 + 10.0 + TRANSFER_PENALTY_S)
    assert leg_a in result.edges and leg_b in result.edges


def test_no_penalty_for_continuing_the_same_route():
    """Two consecutive ride edges on the same route must NOT incur the
    transfer penalty."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    leg1 = _ride_edge(route, s1, s2, duration_s=10.0, to_sequence=2)
    leg2 = _ride_edge(route, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)

    graph = _build_graph([s1, s2, s3], ride_edges=(leg1, leg2))
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s3))

    assert result is not None
    assert result.total_duration_s == pytest.approx(20.0)


def test_no_penalty_for_the_very_first_boarding():
    """Boarding the first ride edge of a journey is not itself a
    'transfer' - there's no prior route being switched away from."""
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride_edge(route, s1, s2, duration_s=42.0)

    graph = _build_graph([s1, s2], ride_edges=(ride,))
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s2))

    assert result is not None
    assert result.total_duration_s == pytest.approx(42.0)


def test_walk_mediated_transfer_between_routes_still_incurs_penalty():
    """S1 --route A--> S2 --walk--> S3 --route B--> S4: walking between
    the two routes' stops must NOT reset the "last route ridden" state -
    the transfer penalty must still apply, exactly as for an immediate
    same-stop transfer."""
    s1, s2, s3, s4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b = uuid.uuid4(), uuid.uuid4()

    leg_a = _ride_edge(route_a, s1, s2, duration_s=30.0)
    walk = _walk_edge(s2, s3, duration_s=40.0)
    leg_b = _ride_edge(route_b, s3, s4, duration_s=30.0)

    graph = _build_graph(
        [s1, s2, s3, s4], ride_edges=(leg_a, leg_b), walk_edges=(walk,)
    )
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s4))

    assert result is not None
    assert result.total_duration_s == pytest.approx(
        30.0 + 40.0 + 30.0 + TRANSFER_PENALTY_S
    )
    assert list(result.edges[1:4]) == [leg_a, walk, leg_b]


def test_walking_back_onto_the_same_route_incurs_no_penalty():
    """S1 --route A--> S2 --walk--> S3 --route A--> S4 (same route both
    times): walking doesn't itself trigger a penalty, and re-boarding the
    SAME route after a walk shouldn't either."""
    s1, s2, s3, s4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    leg_a = _ride_edge(route, s1, s2, duration_s=30.0)
    walk = _walk_edge(s2, s3, duration_s=40.0)
    leg_b = _ride_edge(route, s3, s4, duration_s=30.0)

    graph = _build_graph(
        [s1, s2, s3, s4], ride_edges=(leg_a, leg_b), walk_edges=(walk,)
    )
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s4))

    assert result is not None
    assert result.total_duration_s == pytest.approx(30.0 + 40.0 + 30.0)


# ---------------------------------------------------------------------------
# Disconnected / no-path cases
# ---------------------------------------------------------------------------


def test_returns_none_when_graph_is_disconnected():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    graph = _build_graph([s1, s2])  # no edges at all
    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s2))
    assert result is None


def test_returns_none_when_no_origin_connections():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride_edge(route, s1, s2, duration_s=10.0)
    graph = _build_graph([s1, s2], ride_edges=(ride,))

    result = find_shortest_path(graph, (), _destination_at(s2))
    assert result is None


def test_returns_none_when_no_destination_connections():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride_edge(route, s1, s2, duration_s=10.0)
    graph = _build_graph([s1, s2], ride_edges=(ride,))

    result = find_shortest_path(graph, _origin_at(s1), ())
    assert result is None


def test_returns_none_when_destination_stop_is_reachable_from_a_different_component():
    """S1 and S2 are connected; S3 (destination candidate) is isolated -
    no edge reaches it from anywhere."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride_edge(route, s1, s2, duration_s=10.0)
    graph = _build_graph([s1, s2, s3], ride_edges=(ride,))

    result = find_shortest_path(graph, _origin_at(s1), _destination_at(s3))
    assert result is None


# ---------------------------------------------------------------------------
# Path reconstruction / order
# ---------------------------------------------------------------------------


def test_edges_are_returned_in_correct_travel_order():
    s1, s2, s3, s4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    leg1 = _ride_edge(route, s1, s2, duration_s=10.0, to_sequence=2)
    leg2 = _ride_edge(route, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)
    leg3 = _ride_edge(route, s3, s4, duration_s=10.0, from_sequence=3, to_sequence=4)

    graph = _build_graph([s1, s2, s3, s4], ride_edges=(leg1, leg2, leg3))
    origin_conns = _origin_at(s1, duration_s=5.0)
    dest_conns = _destination_at(s4, duration_s=5.0)

    result = find_shortest_path(graph, origin_conns, dest_conns)

    assert result is not None
    assert result.edges == (origin_conns[0], leg1, leg2, leg3, dest_conns[0])


def test_origin_equals_destination_stop_needs_no_ride_or_walk_edge():
    """Origin and destination both snap to the same stop - a valid
    (if unusual) 2-edge "just walk both ways" path with no bus needed."""
    s1 = uuid.uuid4()
    graph = _build_graph([s1])  # no ride/walk edges at all
    origin_conns = _origin_at(s1, duration_s=30.0)
    dest_conns = _destination_at(s1, duration_s=20.0)

    result = find_shortest_path(graph, origin_conns, dest_conns)

    assert result is not None
    assert result.edges == (origin_conns[0], dest_conns[0])
    assert result.total_duration_s == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# No mutation of the base graph
# ---------------------------------------------------------------------------


def test_search_does_not_mutate_the_base_graph():
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    leg1 = _ride_edge(route, s1, s2, duration_s=10.0, to_sequence=2)
    leg2 = _ride_edge(route, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)
    walk = _walk_edge(s1, s2, duration_s=999.0)

    graph = _build_graph([s1, s2, s3], ride_edges=(leg1, leg2), walk_edges=(walk,))

    nodes_before = graph.nodes
    ride_edges_before = graph.ride_edges
    walk_edges_before = graph.walk_edges
    ride_by_from_before = graph.ride_edges_by_from
    walk_by_from_before = graph.walk_edges_by_from
    ride_edge_count_before = len(graph.ride_edges)
    walk_edge_count_before = len(graph.walk_edges)

    find_shortest_path(graph, _origin_at(s1), _destination_at(s3))
    find_shortest_path(graph, _origin_at(s2), _destination_at(s1))  # a second call too

    # Same *objects*, not just equal-content copies - proves nothing was
    # rebuilt or appended to in place.
    assert graph.nodes is nodes_before
    assert graph.ride_edges is ride_edges_before
    assert graph.walk_edges is walk_edges_before
    assert graph.ride_edges_by_from is ride_by_from_before
    assert graph.walk_edges_by_from is walk_by_from_before
    assert len(graph.ride_edges) == ride_edge_count_before
    assert len(graph.walk_edges) == walk_edge_count_before

    # And the read-only containers still genuinely reject mutation
    # (re-confirming Step 1's guarantee holds after being used here).
    with pytest.raises(TypeError):
        graph.nodes[uuid.uuid4()] = None
    with pytest.raises(AttributeError):
        graph.ride_edges.append(None)


def test_multiple_searches_on_the_same_graph_do_not_interfere():
    """Calling find_shortest_path twice with different origin/destination
    connections on the same graph must not leak state between calls."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    leg1 = _ride_edge(route, s1, s2, duration_s=10.0, to_sequence=2)
    leg2 = _ride_edge(route, s2, s3, duration_s=20.0, from_sequence=2, to_sequence=3)

    graph = _build_graph([s1, s2, s3], ride_edges=(leg1, leg2))

    result_1_to_3 = find_shortest_path(graph, _origin_at(s1), _destination_at(s3))
    result_1_to_2 = find_shortest_path(graph, _origin_at(s1), _destination_at(s2))

    assert result_1_to_3.total_duration_s == pytest.approx(30.0)
    assert result_1_to_2.total_duration_s == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Dataclass / sentinel sanity
# ---------------------------------------------------------------------------


def test_search_result_is_frozen():
    assert SearchResult.__dataclass_params__.frozen is True


def test_origin_and_destination_sentinels_are_distinct_singletons():
    assert ORIGIN is not DESTINATION
    assert repr(ORIGIN) != repr(DESTINATION)
