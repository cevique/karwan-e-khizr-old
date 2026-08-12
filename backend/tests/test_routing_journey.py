"""
Tests for `routing.journey` (WalkLeg/RideLeg/Journey reconstruction).

Like `test_routing_search.py`, these are pure, database-free unit tests:
`routing.journey` has no `async`, no SQLAlchemy, and no FastAPI dependency
by design (this step's explicit requirement), so tests build small
`SearchResult` instances directly by hand - `SearchResult.edges` is just a
tuple of already-existing `OriginConnection`/`RideEdge`/`WalkEdge`/
`DestinationConnection` objects, so no actual search or database access is
needed to exercise the reconstruction logic in isolation.
"""

import uuid

from routing.graph import RideEdge, WalkEdge
from routing.journey import Journey, RideLeg, WalkLeg, build_journey
from routing.search import SearchResult
from routing.snapping import DestinationConnection, OriginConnection

AGENCY_ID = uuid.uuid4()


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
        agency_id=AGENCY_ID,
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


def _origin(to_stop_id: uuid.UUID, distance_m: float, duration_s: float) -> OriginConnection:
    return OriginConnection(to_stop_id=to_stop_id, distance_m=distance_m, duration_s=duration_s)


def _destination(
    from_stop_id: uuid.UUID, distance_m: float, duration_s: float
) -> DestinationConnection:
    return DestinationConnection(
        from_stop_id=from_stop_id, distance_m=distance_m, duration_s=duration_s
    )


def _result(*edges) -> SearchResult:
    # total_duration_s is intentionally a nonsense sentinel value in most
    # tests below - build_journey must compute its own total from the
    # legs, never read SearchResult.total_duration_s (see routing.journey's
    # docstring on why the two are allowed to differ).
    return SearchResult(total_duration_s=-1.0, edges=tuple(edges))


# ---------------------------------------------------------------------------
# Simple walk -> ride -> walk
# ---------------------------------------------------------------------------


def test_simple_walk_ride_walk_journey():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    origin = _origin(s1, distance_m=10.0, duration_s=10.0)
    ride = _ride(route, s1, s2, duration_s=50.0)
    destination = _destination(s2, distance_m=5.0, duration_s=5.0)

    journey = build_journey(_result(origin, ride, destination))

    assert len(journey.legs) == 3
    assert journey.legs[0] == WalkLeg(
        from_stop_id=None, to_stop_id=s1, distance_m=10.0, duration_s=10.0
    )
    assert journey.legs[1] == RideLeg(
        route_id=route,
        agency_id=AGENCY_ID,
        board_stop_id=s1,
        board_sequence=1,
        alight_stop_id=s2,
        alight_sequence=2,
        intermediate_stop_ids=(),
        duration_s=50.0,
    )
    assert journey.legs[2] == WalkLeg(
        from_stop_id=s2, to_stop_id=None, distance_m=5.0, duration_s=5.0
    )
    assert journey.total_duration_s == 65.0
    assert journey.total_walk_m == 15.0
    assert journey.transfer_count == 0


# ---------------------------------------------------------------------------
# Multiple consecutive ride edges -> one RideLeg; intermediate stop ordering
# ---------------------------------------------------------------------------


def test_consecutive_same_route_edges_merge_into_a_single_ride_leg():
    s1, s2, s3, s4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    leg1 = _ride(route, s1, s2, duration_s=10.0, from_sequence=1, to_sequence=2)
    leg2 = _ride(route, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)
    leg3 = _ride(route, s3, s4, duration_s=10.0, from_sequence=3, to_sequence=4)

    journey = build_journey(
        _result(_origin(s1, 0, 0), leg1, leg2, leg3, _destination(s4, 0, 0))
    )

    ride_legs = [leg for leg in journey.legs if isinstance(leg, RideLeg)]
    assert len(ride_legs) == 1
    merged = ride_legs[0]
    assert merged.board_stop_id == s1
    assert merged.board_sequence == 1
    assert merged.alight_stop_id == s4
    assert merged.alight_sequence == 4
    assert merged.duration_s == 30.0
    assert merged.route_id == route
    assert merged.agency_id == AGENCY_ID


def test_intermediate_stop_ordering_is_preserved_across_many_hops():
    stops = [uuid.uuid4() for _ in range(6)]  # s0..s5
    route = uuid.uuid4()

    ride_edges = [
        _ride(route, stops[i], stops[i + 1], duration_s=5.0, from_sequence=i + 1, to_sequence=i + 2)
        for i in range(5)
    ]

    journey = build_journey(
        _result(_origin(stops[0], 0, 0), *ride_edges, _destination(stops[5], 0, 0))
    )

    ride_legs = [leg for leg in journey.legs if isinstance(leg, RideLeg)]
    assert len(ride_legs) == 1
    assert ride_legs[0].board_stop_id == stops[0]
    assert ride_legs[0].alight_stop_id == stops[5]
    assert ride_legs[0].intermediate_stop_ids == tuple(stops[1:5])


def test_single_ride_edge_has_no_intermediate_stops():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride(route, s1, s2, duration_s=20.0)

    journey = build_journey(_result(_origin(s1, 0, 0), ride, _destination(s2, 0, 0)))
    ride_legs = [leg for leg in journey.legs if isinstance(leg, RideLeg)]
    assert ride_legs[0].intermediate_stop_ids == ()


# ---------------------------------------------------------------------------
# Transfers between routes
# ---------------------------------------------------------------------------


def test_same_stop_transfer_produces_two_ride_legs_and_one_transfer():
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b = uuid.uuid4(), uuid.uuid4()

    leg_a = _ride(route_a, s1, s2, duration_s=30.0)
    leg_b = _ride(route_b, s2, s3, duration_s=30.0)

    journey = build_journey(
        _result(_origin(s1, 0, 0), leg_a, leg_b, _destination(s3, 0, 0))
    )

    ride_legs = [leg for leg in journey.legs if isinstance(leg, RideLeg)]
    assert len(ride_legs) == 2
    assert ride_legs[0].route_id == route_a
    assert ride_legs[1].route_id == route_b
    assert journey.transfer_count == 1
    # No WalkLeg between the two RideLegs for a same-stop transfer.
    assert journey.legs == (
        journey.legs[0],
        ride_legs[0],
        ride_legs[1],
        journey.legs[-1],
    )


def test_walk_mediated_transfer_between_different_routes_counts_as_one_transfer():
    s1, s2, s3, s4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route_a, route_b = uuid.uuid4(), uuid.uuid4()

    leg_a = _ride(route_a, s1, s2, duration_s=30.0)
    walk = _walk(s2, s3, duration_s=40.0)
    leg_b = _ride(route_b, s3, s4, duration_s=30.0)

    journey = build_journey(
        _result(_origin(s1, 0, 0), leg_a, walk, leg_b, _destination(s4, 0, 0))
    )

    assert [type(leg).__name__ for leg in journey.legs] == [
        "WalkLeg",
        "RideLeg",
        "WalkLeg",
        "RideLeg",
        "WalkLeg",
    ]
    assert journey.transfer_count == 1
    assert journey.legs[2] == WalkLeg(
        from_stop_id=s2, to_stop_id=s3, distance_m=walk.distance_m, duration_s=40.0
    )


# ---------------------------------------------------------------------------
# Same-route continuation is NOT a transfer
# ---------------------------------------------------------------------------


def test_same_route_continuation_without_a_walk_is_not_a_transfer():
    """Directly consecutive same-route edges must merge into one RideLeg
    (covered above), so there's no adjacency to even miscount - this test
    just confirms transfer_count is 0 in that case too."""
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    leg1 = _ride(route, s1, s2, duration_s=10.0, from_sequence=1, to_sequence=2)
    leg2 = _ride(route, s2, s3, duration_s=10.0, from_sequence=2, to_sequence=3)

    journey = build_journey(
        _result(_origin(s1, 0, 0), leg1, leg2, _destination(s3, 0, 0))
    )
    assert journey.transfer_count == 0


def test_walking_off_and_back_onto_the_same_route_is_not_a_transfer():
    """The tricky case: a WalkEdge forces the two RideEdge runs into
    separate RideLeg objects even though they share the same route_id -
    transfer_count must still be 0, consistent with routing.search's own
    transfer-penalty rule (no penalty for re-boarding the same route)."""
    s1, s2, s3, s4 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()

    leg_a = _ride(route, s1, s2, duration_s=30.0)
    walk = _walk(s2, s3, duration_s=20.0)
    leg_b = _ride(route, s3, s4, duration_s=30.0)

    journey = build_journey(
        _result(_origin(s1, 0, 0), leg_a, walk, leg_b, _destination(s4, 0, 0))
    )

    ride_legs = [leg for leg in journey.legs if isinstance(leg, RideLeg)]
    assert len(ride_legs) == 2  # NOT merged (a WalkEdge sits between them)
    assert journey.transfer_count == 0  # but still not counted as a transfer
    assert journey.total_duration_s == 30.0 + 20.0 + 30.0


# ---------------------------------------------------------------------------
# Origin/destination walking
# ---------------------------------------------------------------------------


def test_origin_and_destination_legs_have_none_on_the_virtual_side():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride(route, s1, s2, duration_s=10.0)

    origin = _origin(s1, distance_m=12.0, duration_s=9.0)
    destination = _destination(s2, distance_m=8.0, duration_s=6.0)
    journey = build_journey(_result(origin, ride, destination))

    first_leg, last_leg = journey.legs[0], journey.legs[-1]
    assert isinstance(first_leg, WalkLeg) and isinstance(last_leg, WalkLeg)
    assert first_leg.from_stop_id is None and first_leg.to_stop_id == s1
    assert first_leg.distance_m == 12.0 and first_leg.duration_s == 9.0
    assert last_leg.from_stop_id == s2 and last_leg.to_stop_id is None
    assert last_leg.distance_m == 8.0 and last_leg.duration_s == 6.0


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def test_aggregate_totals_across_a_multi_leg_journey():
    s1, s2, s3, s4, s5 = (uuid.uuid4() for _ in range(5))
    route_a, route_b = uuid.uuid4(), uuid.uuid4()

    origin = _origin(s1, distance_m=20.0, duration_s=16.0)
    leg_a = _ride(route_a, s1, s2, duration_s=100.0)
    walk = _walk(s2, s3, duration_s=30.0)
    leg_b = _ride(route_b, s3, s4, duration_s=60.0, from_sequence=1, to_sequence=2)
    leg_b2 = _ride(route_b, s4, s5, duration_s=40.0, from_sequence=2, to_sequence=3)
    destination = _destination(s5, distance_m=10.0, duration_s=8.0)

    journey = build_journey(
        _result(origin, leg_a, walk, leg_b, leg_b2, destination)
    )

    # legs: WalkLeg(origin) + RideLeg(A) + WalkLeg(transfer) + RideLeg(B, merged 2 edges) + WalkLeg(dest)
    assert len(journey.legs) == 5
    ride_legs = [leg for leg in journey.legs if isinstance(leg, RideLeg)]
    assert len(ride_legs) == 2
    assert ride_legs[1].duration_s == 100.0  # 60 + 40 merged

    expected_total_duration = 16.0 + 100.0 + 30.0 + 60.0 + 40.0 + 8.0
    expected_total_walk_m = 20.0 + walk.distance_m + 10.0

    assert journey.total_duration_s == expected_total_duration
    assert journey.total_walk_m == expected_total_walk_m
    assert journey.transfer_count == 1


def test_total_walk_m_excludes_ride_leg_distance():
    """A RideLeg has no distance_m field at all - only WalkLegs contribute
    to total_walk_m. This test exists to catch an accidental "sum
    everything with a distance-like field" bug."""
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride(route, s1, s2, duration_s=500.0)  # long ride, no distance_m field

    journey = build_journey(
        _result(_origin(s1, 5.0, 5.0), ride, _destination(s2, 3.0, 3.0))
    )
    assert journey.total_walk_m == 8.0
    assert not hasattr(RideLeg, "distance_m")


# ---------------------------------------------------------------------------
# Edge case: origin and destination are the same stop
# ---------------------------------------------------------------------------


def test_origin_and_destination_resolve_to_the_same_stop():
    s1 = uuid.uuid4()
    origin = _origin(s1, distance_m=30.0, duration_s=30.0)
    destination = _destination(s1, distance_m=20.0, duration_s=20.0)

    journey = build_journey(_result(origin, destination))

    assert journey.legs == (
        WalkLeg(from_stop_id=None, to_stop_id=s1, distance_m=30.0, duration_s=30.0),
        WalkLeg(from_stop_id=s1, to_stop_id=None, distance_m=20.0, duration_s=20.0),
    )
    assert journey.total_duration_s == 50.0
    assert journey.total_walk_m == 50.0
    assert journey.transfer_count == 0
    assert not any(isinstance(leg, RideLeg) for leg in journey.legs)


# ---------------------------------------------------------------------------
# Dataclass sanity
# ---------------------------------------------------------------------------


def test_dataclasses_are_frozen():
    for cls in (WalkLeg, RideLeg, Journey):
        assert cls.__dataclass_params__.frozen is True


def test_journey_legs_is_a_tuple_not_a_list():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    route = uuid.uuid4()
    ride = _ride(route, s1, s2, duration_s=10.0)
    journey = build_journey(_result(_origin(s1, 0, 0), ride, _destination(s2, 0, 0)))
    assert isinstance(journey.legs, tuple)
