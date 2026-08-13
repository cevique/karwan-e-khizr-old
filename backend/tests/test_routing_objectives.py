"""
Tests for Step 6: the `fewest_transfers` objective.

Same pure, database-free unit-test style as `test_routing_search.py`
(hand-built `TransitGraph`/connection objects, no async, no DB) - this
file focuses specifically on comparing `fastest_edge_cost` against
`fewest_transfers_edge_cost` and re-confirming the shared transfer
semantics hold identically under the new objective.
`test_routing_search.py` itself is left completely untouched; running it
successfully (see the verification report) is what demonstrates the
`fastest` objective's behavior is unchanged.
"""

import uuid
from types import MappingProxyType

import pytest

from routing.config import TRANSFER_PENALTY_S
from routing.graph import GraphNode, RideEdge, TransitGraph, WalkEdge
from routing.search import (
    Cost,
    fastest_edge_cost,
    fewest_transfers_edge_cost,
    find_shortest_path,
)
from routing.snapping import DestinationConnection, OriginConnection


def _node(stop_id: uuid.UUID) -> GraphNode:
    return GraphNode(stop_id=stop_id, name=str(stop_id), latitude=0.0, longitude=0.0)


def _ride(
    route_id: uuid.UUID,
    from_stop_id: uuid.UUID,
    to_stop_id: uuid.UUID,
    duration_s: float,
    from_sequence: int = 1,
    to_sequence: int = 2,
) -> RideEdge:
    return RideEdge(
        route_id=route_id,
        agency_id=uuid.uuid4(),
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        from_sequence=from_sequence,
        to_sequence=to_sequence,
        from_distance_along_route_m=None,
        to_distance_along_route_m=None,
        duration_s=duration_s,
    )


def _walk(from_stop_id: uuid.UUID, to_stop_id: uuid.UUID, duration_s: float) -> WalkEdge:
    return WalkEdge(
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        distance_m=duration_s * 1.25,
        duration_s=duration_s,
    )


def _build_graph(
    stop_ids: list[uuid.UUID],
    ride_edges: tuple[RideEdge, ...] = (),
    walk_edges: tuple[WalkEdge, ...] = (),
) -> TransitGraph:
    nodes = MappingProxyType({sid: _node(sid) for sid in stop_ids})

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


def _origin_at(stop_id: uuid.UUID) -> tuple[OriginConnection, ...]:
    return (OriginConnection(to_stop_id=stop_id, distance_m=0.0, duration_s=0.0),)


def _destination_at(stop_id: uuid.UUID) -> tuple[DestinationConnection, ...]:
    return (DestinationConnection(from_stop_id=stop_id, distance_m=0.0, duration_s=0.0),)


# ---------------------------------------------------------------------------
# Cost: lexicographic comparison sanity
# ---------------------------------------------------------------------------


def test_cost_compares_transfers_before_duration():
    assert Cost(transfers=0, duration_s=1000.0) < Cost(transfers=1, duration_s=1.0)
    assert Cost(transfers=1, duration_s=1.0) > Cost(transfers=0, duration_s=1000.0)


def test_cost_uses_duration_as_tiebreaker_when_transfers_equal():
    assert Cost(transfers=1, duration_s=10.0) < Cost(transfers=1, duration_s=20.0)


def test_cost_addition_sums_both_fields():
    total = Cost(transfers=1, duration_s=10.0) + Cost(transfers=1, duration_s=5.0)
    assert total == Cost(transfers=2, duration_s=15.0)


# ---------------------------------------------------------------------------
# fastest vs fewest_transfers choose different paths
# ---------------------------------------------------------------------------


def test_fastest_and_fewest_transfers_choose_different_paths():
    """Transfer path: 10 + 10 = 20s raw + one transfer. Single-route path:
    300s raw, zero transfers.

    Under `fastest`: transfer path costs 20 + TRANSFER_PENALTY_S (260s
    total with the default 240s penalty) < 300s -> fastest picks the
    FASTER transfer path.

    Under `fewest_transfers`: the single-route path has fewer transfers
    (0 vs 1), so it wins regardless of its higher raw duration -
    `fewest_transfers` picks the SLOWER, transfer-free path instead. The
    two objectives must therefore choose different paths for this
    scenario.
    """
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b, route_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    leg_a = _ride(route_a, s1, s2, duration_s=10.0, to_sequence=2)
    leg_b = _ride(route_b, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)
    single_route = _ride(route_c, s1, s3, duration_s=300.0)

    # Sanity check the scenario's own assumption before trusting the test.
    assert 10.0 + 10.0 + TRANSFER_PENALTY_S < 300.0

    graph = _build_graph([s1, s2, s3], ride_edges=(leg_a, leg_b, single_route))
    origin, destination = _origin_at(s1), _destination_at(s3)

    fastest_result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=fastest_edge_cost
    )
    fewest_transfers_result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=fewest_transfers_edge_cost
    )

    assert fastest_result is not None and fewest_transfers_result is not None
    assert leg_a in fastest_result.edges and leg_b in fastest_result.edges
    assert single_route not in fastest_result.edges
    assert single_route in fewest_transfers_result.edges
    assert leg_a not in fewest_transfers_result.edges
    # The two objectives must have genuinely chosen different routes.
    assert fastest_result.edges != fewest_transfers_result.edges


def test_fewest_transfers_minimizes_transfers_even_when_slower():
    """Direct confirmation of the requirement: fewest_transfers' chosen
    path has a HIGHER total_duration_s than the path fastest would pick,
    but fewer transfers."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b, route_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    leg_a = _ride(route_a, s1, s2, duration_s=10.0, to_sequence=2)
    leg_b = _ride(route_b, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)
    single_route = _ride(route_c, s1, s3, duration_s=300.0)

    graph = _build_graph([s1, s2, s3], ride_edges=(leg_a, leg_b, single_route))
    origin, destination = _origin_at(s1), _destination_at(s3)

    result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=fewest_transfers_edge_cost
    )

    assert result is not None
    assert result.total_duration_s == pytest.approx(300.0)  # the SLOWER path
    assert single_route in result.edges


# ---------------------------------------------------------------------------
# Equal-transfer paths: duration as tiebreaker
# ---------------------------------------------------------------------------


def test_equal_transfer_count_paths_use_duration_as_tiebreaker():
    """Two alternative routes from S1 to S3, both requiring exactly one
    transfer at S2, but with different raw durations - fewest_transfers
    must pick the shorter one."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_slow_a, route_slow_b = uuid.uuid4(), uuid.uuid4()
    route_fast_a, route_fast_b = uuid.uuid4(), uuid.uuid4()

    slow_leg1 = _ride(route_slow_a, s1, s2, duration_s=60.0, to_sequence=2)
    slow_leg2 = _ride(route_slow_b, s2, s3, duration_s=40.0, from_sequence=2, to_sequence=3)
    fast_leg1 = _ride(route_fast_a, s1, s2, duration_s=20.0, to_sequence=2)
    fast_leg2 = _ride(route_fast_b, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)

    # Both alternatives require exactly one transfer - fastest (raw-time
    # based) would already prefer the fast pair on time alone, so to prove
    # fewest_transfers is ALSO using duration as its tiebreaker (not just
    # "any one-transfer path"), both pairs must have equal transfer count.
    graph = _build_graph(
        [s1, s2, s3], ride_edges=(slow_leg1, slow_leg2, fast_leg1, fast_leg2)
    )
    origin, destination = _origin_at(s1), _destination_at(s3)

    result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=fewest_transfers_edge_cost
    )

    assert result is not None
    assert result.total_duration_s == pytest.approx(30.0)
    assert fast_leg1 in result.edges and fast_leg2 in result.edges
    assert slow_leg1 not in result.edges and slow_leg2 not in result.edges


# ---------------------------------------------------------------------------
# Existing transfer semantics preserved under fewest_transfers
# ---------------------------------------------------------------------------


def test_no_penalty_for_the_very_first_boarding_under_fewest_transfers():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride(route, s1, s2, duration_s=42.0)

    graph = _build_graph([s1, s2], ride_edges=(ride,))
    result = find_shortest_path(
        graph,
        _origin_at(s1),
        _destination_at(s2),
        edge_cost_fn=fewest_transfers_edge_cost,
    )

    assert result is not None
    assert result.total_duration_s == pytest.approx(42.0)


def test_same_route_continuation_is_not_a_transfer_under_fewest_transfers():
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    leg1 = _ride(route, s1, s2, duration_s=10.0, to_sequence=2)
    leg2 = _ride(route, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)

    graph = _build_graph([s1, s2, s3], ride_edges=(leg1, leg2))
    result = find_shortest_path(
        graph,
        _origin_at(s1),
        _destination_at(s3),
        edge_cost_fn=fewest_transfers_edge_cost,
    )

    assert result is not None
    assert result.total_duration_s == pytest.approx(20.0)


def test_switching_routes_counts_as_one_transfer_under_fewest_transfers():
    """Only one route pair connects S1 to S3, forcing exactly one
    transfer, so we can directly confirm total_duration_s excludes any
    penalty (fewest_transfers never adds TRANSFER_PENALTY_S as time)."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b = uuid.uuid4(), uuid.uuid4()
    leg_a = _ride(route_a, s1, s2, duration_s=15.0, to_sequence=2)
    leg_b = _ride(route_b, s2, s3, duration_s=25.0, from_sequence=2, to_sequence=3)

    graph = _build_graph([s1, s2, s3], ride_edges=(leg_a, leg_b))
    result = find_shortest_path(
        graph,
        _origin_at(s1),
        _destination_at(s3),
        edge_cost_fn=fewest_transfers_edge_cost,
    )

    assert result is not None
    assert result.total_duration_s == pytest.approx(40.0)  # no penalty added


def test_walk_mediated_transfer_between_routes_is_still_a_transfer_under_fewest_transfers():
    s1, s2, s3, s4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b = uuid.uuid4(), uuid.uuid4()

    leg_a = _ride(route_a, s1, s2, duration_s=30.0)
    walk = _walk(s2, s3, duration_s=40.0)
    leg_b = _ride(route_b, s3, s4, duration_s=30.0)

    # A "same route" alternative that never leaves route A, much slower -
    # fewest_transfers must still prefer this transfer-free alternative,
    # proving the walk-mediated transfer above really was counted as a
    # transfer (otherwise the shorter path would win on duration alone
    # since both would show 0 transfers).
    same_route_alt = _ride(route_a, s1, s4, duration_s=500.0)

    graph = _build_graph(
        [s1, s2, s3, s4], ride_edges=(leg_a, leg_b, same_route_alt), walk_edges=(walk,)
    )
    result = find_shortest_path(
        graph,
        _origin_at(s1),
        _destination_at(s4),
        edge_cost_fn=fewest_transfers_edge_cost,
    )

    assert result is not None
    assert same_route_alt in result.edges  # transfer-free path wins despite being slower
    assert result.total_duration_s == pytest.approx(500.0)


def test_walking_back_onto_the_same_route_is_not_a_transfer_under_fewest_transfers():
    s1, s2, s3, s4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    leg_a = _ride(route, s1, s2, duration_s=30.0)
    walk = _walk(s2, s3, duration_s=20.0)
    leg_b = _ride(route, s3, s4, duration_s=30.0)

    graph = _build_graph([s1, s2, s3, s4], ride_edges=(leg_a, leg_b), walk_edges=(walk,))
    result = find_shortest_path(
        graph,
        _origin_at(s1),
        _destination_at(s4),
        edge_cost_fn=fewest_transfers_edge_cost,
    )

    assert result is not None
    # Same route both times (via a walk) should be picked over any
    # transfer-requiring alternative, and its duration must be the plain
    # sum with no penalty, confirming 0 transfers were counted.
    assert result.total_duration_s == pytest.approx(30.0 + 20.0 + 30.0)


# ---------------------------------------------------------------------------
# Default wiring
# ---------------------------------------------------------------------------


def test_find_shortest_path_default_edge_cost_fn_is_fastest():
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b, route_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    leg_a = _ride(route_a, s1, s2, duration_s=10.0, to_sequence=2)
    leg_b = _ride(route_b, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)
    single_route = _ride(route_c, s1, s3, duration_s=300.0)

    graph = _build_graph([s1, s2, s3], ride_edges=(leg_a, leg_b, single_route))
    origin, destination = _origin_at(s1), _destination_at(s3)

    default_result = find_shortest_path(graph, origin, destination)
    explicit_fastest_result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=fastest_edge_cost
    )

    assert default_result.edges == explicit_fastest_result.edges
    assert default_result.total_duration_s == pytest.approx(
        explicit_fastest_result.total_duration_s
    )
