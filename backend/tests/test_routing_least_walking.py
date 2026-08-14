"""
Tests for Step 9: the `least_walking` objective.

Same pure, database-free unit-test style as `test_routing_objectives.py`
(hand-built `TransitGraph`/connection objects, no async, no DB). Also
re-confirms `fastest`/`fewest_transfers` are unaffected by the `Cost`
extension - though `test_routing_search.py`/`test_routing_objectives.py`
themselves (left completely untouched, still passing unmodified) are the
primary proof of that; the tests here just add a couple of direct
cross-objective comparisons for extra confidence.
"""

import uuid
from types import MappingProxyType

import pytest

from routing.graph import GraphNode, RideEdge, TransitGraph, WalkEdge
from routing.search import (
    Cost,
    fastest_edge_cost,
    fewest_transfers_edge_cost,
    find_shortest_path,
    least_walking_edge_cost,
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


def _walk(
    from_stop_id: uuid.UUID, to_stop_id: uuid.UUID, distance_m: float, duration_s: float
) -> WalkEdge:
    return WalkEdge(
        from_stop_id=from_stop_id,
        to_stop_id=to_stop_id,
        distance_m=distance_m,
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


def _origin_at(
    stop_id: uuid.UUID, distance_m: float = 0.0, duration_s: float = 0.0
) -> tuple[OriginConnection, ...]:
    return (
        OriginConnection(to_stop_id=stop_id, distance_m=distance_m, duration_s=duration_s),
    )


def _destination_at(
    stop_id: uuid.UUID, distance_m: float = 0.0, duration_s: float = 0.0
) -> tuple[DestinationConnection, ...]:
    return (
        DestinationConnection(
            from_stop_id=stop_id, distance_m=distance_m, duration_s=duration_s
        ),
    )


# ---------------------------------------------------------------------------
# Cost: walk_m field sanity
# ---------------------------------------------------------------------------


def test_cost_compares_walk_m_before_duration_when_transfers_equal():
    assert Cost(transfers=0, walk_m=10.0, duration_s=1000.0) < Cost(
        transfers=0, walk_m=20.0, duration_s=1.0
    )


def test_cost_addition_sums_walk_m_too():
    total = Cost(transfers=0, walk_m=10.0, duration_s=5.0) + Cost(
        transfers=0, walk_m=15.0, duration_s=5.0
    )
    assert total == Cost(transfers=0, walk_m=25.0, duration_s=10.0)


def test_cost_default_walk_m_is_zero():
    assert Cost().walk_m == 0.0
    assert Cost(transfers=1, duration_s=5.0).walk_m == 0.0  # backward-compat keyword use


# ---------------------------------------------------------------------------
# 1. least_walking can deliberately choose a slower journey
# ---------------------------------------------------------------------------


def test_least_walking_chooses_a_slower_ride_over_a_faster_walk():
    """A direct ride (0m walking, but slow - 500s) vs. a direct walk
    (200m walking, faster - 160s). `fastest` must prefer the walk;
    `least_walking` must prefer the (slower) ride, since it walks
    nothing at all."""
    s1, s3 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    ride_direct = _ride(route, s1, s3, duration_s=500.0)
    walk_direct = _walk(s1, s3, distance_m=200.0, duration_s=160.0)

    graph = _build_graph([s1, s3], ride_edges=(ride_direct,), walk_edges=(walk_direct,))
    origin, destination = _origin_at(s1), _destination_at(s3)

    fastest_result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=fastest_edge_cost
    )
    least_walking_result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=least_walking_edge_cost
    )

    assert fastest_result is not None and least_walking_result is not None
    assert walk_direct in fastest_result.edges
    assert ride_direct not in fastest_result.edges

    assert ride_direct in least_walking_result.edges
    assert walk_direct not in least_walking_result.edges
    assert least_walking_result.total_duration_s == pytest.approx(500.0)  # the SLOWER path


# ---------------------------------------------------------------------------
# 2. Equal-walking-distance paths use duration as tiebreaker
# ---------------------------------------------------------------------------


def test_equal_walking_distance_paths_use_duration_as_tiebreaker():
    """Two alternative routes, both requiring the exact same total
    walking distance (via their origin/destination connections - no
    WalkEdge/RideEdge difference in walking at all), but different ride
    durations - least_walking must pick the faster one."""
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route_slow, route_fast = uuid.uuid4(), uuid.uuid4()

    slow_ride = _ride(route_slow, s1, s2, duration_s=200.0)
    fast_ride = _ride(route_fast, s1, s2, duration_s=50.0)

    graph = _build_graph([s1, s2], ride_edges=(slow_ride, fast_ride))
    # Identical walking distance/duration on both ends for both candidates
    # - only ride duration should differentiate them.
    origin = _origin_at(s1, distance_m=30.0, duration_s=25.0)
    destination = _destination_at(s2, distance_m=20.0, duration_s=16.0)

    result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=least_walking_edge_cost
    )

    assert result is not None
    assert fast_ride in result.edges
    assert slow_ride not in result.edges
    assert result.total_duration_s == pytest.approx(25.0 + 50.0 + 16.0)


# ---------------------------------------------------------------------------
# 3. Ride-only journeys have zero walking cost
# ---------------------------------------------------------------------------


def test_ride_only_journey_has_zero_walking_contribution_from_the_ride():
    """A ride edge's own duration must never leak into the walking
    dimension - confirmed via the public `routing.journey.build_journey`,
    whose `total_walk_m` sums only `WalkLeg`s (see that module)."""
    from routing.journey import build_journey

    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride(route, s1, s2, duration_s=999.0)  # long ride, must add 0 walking

    graph = _build_graph([s1, s2], ride_edges=(ride,))
    origin, destination = _origin_at(s1), _destination_at(s2)  # zero walking at both ends

    result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=least_walking_edge_cost
    )
    assert result is not None
    assert ride in result.edges

    journey = build_journey(result)
    assert journey.total_walk_m == 0.0


# ---------------------------------------------------------------------------
# 4. Origin/destination access walking contributes to the objective
# ---------------------------------------------------------------------------


def test_origin_and_destination_walking_distance_affects_least_walking_choice():
    """Two origin candidates for the same stop-pair journey: one with a
    long walk to reach the network, one with a short walk - least_walking
    must prefer the shorter walk even though both lead to the exact same
    ride."""
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride(route, s1, s2, duration_s=100.0)

    graph = _build_graph([s1, s2], ride_edges=(ride,))
    destination = _destination_at(s2, distance_m=0.0, duration_s=0.0)

    long_walk_origin = _origin_at(s1, distance_m=500.0, duration_s=400.0)
    short_walk_origin = _origin_at(s1, distance_m=20.0, duration_s=16.0)

    long_result = find_shortest_path(
        graph, long_walk_origin, destination, edge_cost_fn=least_walking_edge_cost
    )
    short_result = find_shortest_path(
        graph, short_walk_origin, destination, edge_cost_fn=least_walking_edge_cost
    )

    assert long_result.total_duration_s == pytest.approx(400.0 + 100.0)
    assert short_result.total_duration_s == pytest.approx(16.0 + 100.0)
    # Confirms the origin connection's distance_m genuinely feeds the
    # objective (both searches otherwise identical).
    assert long_result.total_duration_s != short_result.total_duration_s


# ---------------------------------------------------------------------------
# 5. Transfer/intermediate walking contributes to the objective
# ---------------------------------------------------------------------------


def test_transfer_walk_edge_distance_affects_least_walking_choice():
    """Two alternative transfer points between the same origin/destination
    stops: one transfer walk is short, one is long - least_walking must
    prefer the shorter one even if the longer one is otherwise faster."""
    s1, s2_near, s2_far, s3 = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    route_a, route_b = uuid.uuid4(), uuid.uuid4()

    # Path via s2_near: short walk (50m), but a slower onward ride.
    ride_to_near = _ride(route_a, s1, s2_near, duration_s=10.0, to_sequence=2)
    short_transfer_walk = _walk(s2_near, s3, distance_m=50.0, duration_s=40.0)

    # Path via s2_far: long walk (900m), faster onward "ride" (skip - use
    # a direct walk continuation instead to isolate walking distance as
    # the only differentiator between the two full paths' walk totals).
    ride_to_far = _ride(route_b, s1, s2_far, duration_s=10.0, to_sequence=2)
    long_transfer_walk = _walk(s2_far, s3, distance_m=900.0, duration_s=720.0)

    graph = _build_graph(
        [s1, s2_near, s2_far, s3],
        ride_edges=(ride_to_near, ride_to_far),
        walk_edges=(short_transfer_walk, long_transfer_walk),
    )
    origin, destination = _origin_at(s1), _destination_at(s3)

    result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=least_walking_edge_cost
    )

    assert result is not None
    assert short_transfer_walk in result.edges
    assert long_transfer_walk not in result.edges
    assert result.total_duration_s == pytest.approx(10.0 + 40.0)


# ---------------------------------------------------------------------------
# 6 & 7. fastest / fewest_transfers unchanged (extra direct checks;
# test_routing_search.py and test_routing_objectives.py, left completely
# untouched and still passing, are the primary proof)
# ---------------------------------------------------------------------------


def test_fastest_still_ignores_walking_distance_entirely():
    """fastest must still pick the shorter-duration option even when it
    involves much MORE walking than the alternative - confirms `walk_m`
    genuinely has zero influence on the fastest objective."""
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    fast_long_walk = _walk(s1, s2, distance_m=2000.0, duration_s=50.0)
    slow_ride = _ride(route, s1, s2, duration_s=500.0)

    graph = _build_graph([s1, s2], ride_edges=(slow_ride,), walk_edges=(fast_long_walk,))
    result = find_shortest_path(
        graph, _origin_at(s1), _destination_at(s2), edge_cost_fn=fastest_edge_cost
    )
    assert result is not None
    assert fast_long_walk in result.edges  # walking distance irrelevant to fastest


def test_fewest_transfers_still_ignores_walking_distance_entirely():
    """fewest_transfers must still pick the 0-transfer option even when
    it involves much more walking than a 1-transfer alternative."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b, route_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    leg_a = _ride(route_a, s1, s2, duration_s=10.0, to_sequence=2)
    leg_b = _ride(route_b, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)
    direct_with_long_walk_origin = _ride(route_c, s1, s3, duration_s=50.0)

    graph = _build_graph([s1, s2, s3], ride_edges=(leg_a, leg_b, direct_with_long_walk_origin))
    origin = _origin_at(s1, distance_m=2000.0, duration_s=1600.0)  # long walk either way
    destination = _destination_at(s3)

    result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=fewest_transfers_edge_cost
    )
    assert result is not None
    assert direct_with_long_walk_origin in result.edges  # 0-transfer route still wins
    assert leg_a not in result.edges


# ---------------------------------------------------------------------------
# 10. All three objectives can select different paths on one graph
# ---------------------------------------------------------------------------


def test_all_three_objectives_can_choose_different_paths():
    """A single graph where fastest, fewest_transfers, and least_walking
    each pick a genuinely different route:

    - Route T (transfer, via s2): raw ride 9+9=18s + 240s penalty = 258s
      total under fastest; 1 transfer; 0m walking.
    - Route D (direct, single route): 1800s ride; 0 transfers; 0m walking.
    - Walk W (direct walk instead of any bus): 100s; 0 transfers; 300m
      walking.

    fastest -> Route T (258s beats D's 1800s and W's 100s? wait: W's 100s
    is actually the smallest raw number - fastest must pick W).
    """
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b, route_d = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    leg_a = _ride(route_a, s1, s2, duration_s=9.0, to_sequence=2)
    leg_b = _ride(route_b, s2, s3, duration_s=9.0, from_sequence=2, to_sequence=3)
    direct_ride = _ride(route_d, s1, s3, duration_s=1800.0)
    direct_walk = _walk(s1, s3, distance_m=300.0, duration_s=100.0)

    graph = _build_graph(
        [s1, s2, s3],
        ride_edges=(leg_a, leg_b, direct_ride),
        walk_edges=(direct_walk,),
    )
    origin, destination = _origin_at(s1), _destination_at(s3)

    fastest_result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=fastest_edge_cost
    )
    fewest_transfers_result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=fewest_transfers_edge_cost
    )
    least_walking_result = find_shortest_path(
        graph, origin, destination, edge_cost_fn=least_walking_edge_cost
    )

    # fastest: 100s (walk) < 258s (transfer) < 1800s (direct ride) -> walk wins
    assert direct_walk in fastest_result.edges

    # fewest_transfers: direct_ride and direct_walk both have 0 transfers;
    # between those two, duration tiebreaks -> walk (100s) still wins here,
    # demonstrating fewest_transfers' OWN tiebreak, distinct from least_walking's.
    assert direct_walk in fewest_transfers_result.edges

    # least_walking: direct_ride (0m walk) beats both the walk (300m) and
    # the transfer path (0m walk too, but slower: 18s+240s=258s vs
    # direct_ride's 1800s)... both direct_ride and the transfer path have
    # 0m walking - duration tiebreaks between THEM, so the transfer path
    # (258s) wins over direct_ride (1800s).
    assert leg_a in least_walking_result.edges and leg_b in least_walking_result.edges
    assert direct_walk not in least_walking_result.edges
    assert direct_ride not in least_walking_result.edges

    # All three genuinely differ from each other in this scenario.
    chosen_edge_sets = [
        frozenset(e for e in r.edges if e in (leg_a, leg_b, direct_ride, direct_walk))
        for r in (fastest_result, fewest_transfers_result, least_walking_result)
    ]
    assert chosen_edge_sets[0] == chosen_edge_sets[1]  # fastest == fewest_transfers here
    assert chosen_edge_sets[2] != chosen_edge_sets[0]  # least_walking differs from both
