"""
Pure unit tests for the route-geometry-aware interpolation path added in
Phase 4 (plan.md section F): `simulation.geo.point_along_polyline` and
`simulation.engine.compute_position_at`'s `route_geometry` parameter.

No database, no FastAPI - `route_geometry` here is always a synthetic,
hand-built polyline, never a value actually loaded from `Route.path`.
This is deliberate: as of the Phase 3 handoff in plan.md, ZERO real
routes in the canonical dataset have geometry yet (no route's full stop
sequence is located), so there is no live data to exercise this against
in ANY environment right now - these tests are what actually prove the
mechanism works, independent of that.
"""

from __future__ import annotations

import uuid

import pytest

from simulation.engine import (
    AT_STOP,
    COMPLETED,
    EN_ROUTE,
    NOT_STARTED,
    ScheduleStop,
    TripSchedule,
    compute_position_at,
)
from simulation.geo import Point, compute_bearing, interpolate_point, point_along_polyline

# ---------------------------------------------------------------------------
# simulation.geo.point_along_polyline
# ---------------------------------------------------------------------------


def test_point_along_polyline_at_start_and_end():
    polyline = [Point(0.0, 0.0), Point(0.0, 1.0), Point(0.0, 2.0)]
    start, end = Point(0.0, 0.0), Point(0.0, 2.0)

    at_start = point_along_polyline(polyline, start, end, 0.0)
    at_end = point_along_polyline(polyline, start, end, 1.0)

    assert at_start is not None
    assert at_end is not None
    assert at_start[0] == pytest.approx(Point(0.0, 0.0))
    assert at_end[0] == pytest.approx(Point(0.0, 2.0))


def test_point_along_polyline_follows_a_bend_not_a_straight_line():
    """A polyline that bends (e.g. a road going around a corner) must be
    followed, not shortcut - the interpolated point at the midpoint
    fraction should sit ON the polyline's bend, not on the straight
    chord between start and end."""
    polyline = [Point(0.0, 0.0), Point(1.0, 0.0), Point(1.0, 1.0)]
    start, end = Point(0.0, 0.0), Point(1.0, 1.0)

    # Arc length: 0->1 (lat) = ~111.2km, 1->2 (lon) = ~111.2km at lat=1;
    # roughly equal legs, so fraction 0.5 lands close to the bend vertex.
    result = point_along_polyline(polyline, start, end, 0.5)
    assert result is not None
    point, _bearing = result

    straight_chord_midpoint = interpolate_point(start, end, 0.5)
    # The polyline-following point must NOT equal the straight-line
    # midpoint (which would cut across the bend) - it should be much
    # closer to the actual corner vertex (1.0, 0.0).
    assert point != pytest.approx(straight_chord_midpoint, abs=1e-3)
    assert point.latitude == pytest.approx(1.0, abs=0.05)


def test_point_along_polyline_bearing_matches_local_segment_direction():
    polyline = [Point(0.0, 0.0), Point(0.0, 1.0), Point(1.0, 1.0)]
    start, end = Point(0.0, 0.0), Point(1.0, 1.0)

    early = point_along_polyline(polyline, start, end, 0.1)
    late = point_along_polyline(polyline, start, end, 0.9)
    assert early is not None and late is not None

    # Early in the route: still on the eastbound leg (bearing ~90).
    assert early[1] == pytest.approx(90.0, abs=1.0)
    # Late in the route: on the northbound leg (bearing ~0).
    assert late[1] == pytest.approx(0.0, abs=1.0)


def test_point_along_polyline_clamps_fraction_outside_zero_one():
    polyline = [Point(0.0, 0.0), Point(0.0, 2.0)]
    start, end = Point(0.0, 0.0), Point(0.0, 2.0)

    below = point_along_polyline(polyline, start, end, -1.0)
    above = point_along_polyline(polyline, start, end, 2.0)
    assert below is not None and above is not None
    assert below[0] == pytest.approx(start)
    assert above[0] == pytest.approx(end)


def test_point_along_polyline_returns_none_when_end_precedes_start():
    """The polyline runs the OTHER way (or doesn't cover this stop pair
    in order) - must not fabricate a wrong-direction interpolation."""
    polyline = [Point(0.0, 0.0), Point(0.0, 1.0), Point(0.0, 2.0)]
    # start/end reversed relative to the polyline's own direction.
    result = point_along_polyline(polyline, Point(0.0, 2.0), Point(0.0, 0.0), 0.5)
    assert result is None


def test_point_along_polyline_returns_none_for_degenerate_polyline():
    assert point_along_polyline([Point(0.0, 0.0)], Point(0.0, 0.0), Point(0.0, 1.0), 0.5) is None
    assert point_along_polyline([], Point(0.0, 0.0), Point(0.0, 1.0), 0.5) is None


def test_point_along_polyline_returns_none_when_stops_snap_to_same_vertex():
    polyline = [Point(0.0, 0.0), Point(0.0, 1.0)]
    # Both "stops" are closest to the same single vertex - no meaningful
    # sub-path exists between them.
    result = point_along_polyline(polyline, Point(0.0, 0.001), Point(0.0, 0.002), 0.5)
    assert result is None


# ---------------------------------------------------------------------------
# simulation.engine.compute_position_at(..., route_geometry=...)
# ---------------------------------------------------------------------------


def _two_stop_schedule():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    schedule = TripSchedule(
        trip_id=uuid.uuid4(),
        route_id=uuid.uuid4(),
        stops=(
            ScheduleStop(s1, 1, 0.0, 0.0, arrival_offset_s=0, departure_offset_s=0),
            ScheduleStop(s2, 2, 1.0, 1.0, arrival_offset_s=200, departure_offset_s=200),
        ),
    )
    return schedule, (s1, s2)


def test_compute_position_at_none_route_geometry_reproduces_straight_line_behavior():
    """The default (`route_geometry=None`) must be byte-for-byte
    identical to pre-Phase-4 behavior - this is the regression guard for
    "additive, not a replacement" (plan.md section F)."""
    schedule, _ = _two_stop_schedule()
    with_none = compute_position_at(schedule, 100.0, route_geometry=None)
    without_param = compute_position_at(schedule, 100.0)
    assert with_none.latitude == without_param.latitude
    assert with_none.longitude == without_param.longitude
    assert with_none.bearing == without_param.bearing
    assert with_none.speed_kmh == without_param.speed_kmh


def test_compute_position_at_follows_route_geometry_when_en_route():
    """With a bending polyline supplied, the en-route position should sit
    on the bend, not on the straight chord between the two stops -
    proof the engine actually used `route_geometry`, not just the
    stop-to-stop straight line."""
    schedule, (s1, s2) = _two_stop_schedule()
    # A polyline that goes north first, then east - very different from
    # the direct diagonal chord from (0,0) to (1,1).
    route_geometry = [Point(0.0, 0.0), Point(1.0, 0.0), Point(1.0, 1.0)]

    position = compute_position_at(schedule, 100.0, route_geometry=route_geometry)
    assert position.status == EN_ROUTE

    straight_line_equivalent = compute_position_at(schedule, 100.0, route_geometry=None)
    assert (position.latitude, position.longitude) != pytest.approx(
        (straight_line_equivalent.latitude, straight_line_equivalent.longitude)
    )
    # Roughly on/near the bend at this fraction, not on the diagonal.
    assert position.latitude > straight_line_equivalent.latitude


def test_compute_position_at_falls_back_to_straight_line_when_geometry_does_not_cover_stops():
    """A `route_geometry` that doesn't actually run from stop 1 to stop 2
    in order (e.g. mismatched/wrong route's geometry) must not be forced
    - the engine falls back to straight-line interpolation exactly as if
    no geometry had been supplied, rather than fabricating a
    wrong-direction position."""
    schedule, _ = _two_stop_schedule()
    backwards_geometry = [Point(1.0, 1.0), Point(0.5, 0.5), Point(0.0, 0.0)]

    with_bad_geometry = compute_position_at(schedule, 100.0, route_geometry=backwards_geometry)
    straight_line = compute_position_at(schedule, 100.0, route_geometry=None)

    assert with_bad_geometry.latitude == pytest.approx(straight_line.latitude)
    assert with_bad_geometry.longitude == pytest.approx(straight_line.longitude)
    assert with_bad_geometry.bearing == pytest.approx(straight_line.bearing)


def test_compute_position_at_route_geometry_only_affects_en_route_case():
    """`route_geometry` must not change `not_started`/`at_stop`/
    `completed` positions or bearings - those are always exactly at a
    stop's own coordinates, geometry or not."""
    schedule, _ = _two_stop_schedule()
    route_geometry = [Point(0.0, 0.0), Point(1.0, 0.0), Point(1.0, 1.0)]

    for elapsed_s in (-10.0, 0.0, 200.0, 1000.0):
        with_geometry = compute_position_at(schedule, elapsed_s, route_geometry=route_geometry)
        without_geometry = compute_position_at(schedule, elapsed_s, route_geometry=None)
        assert with_geometry.status in (NOT_STARTED, AT_STOP, COMPLETED)
        assert (with_geometry.latitude, with_geometry.longitude) == (
            without_geometry.latitude,
            without_geometry.longitude,
        )


def test_compute_position_at_bearing_follows_local_polyline_segment():
    """The bearing while en route should reflect the CURRENT polyline
    segment's direction (via `point_along_polyline`), not the overall
    stop-to-stop straight-line bearing, when the two differ."""
    schedule, _ = _two_stop_schedule()
    # Early in the trip: on the northbound leg of a north-then-east route.
    route_geometry = [Point(0.0, 0.0), Point(1.0, 0.0), Point(1.0, 1.0)]

    # elapsed_s=20 is early in the 0-200s segment -> low fraction -> still
    # on the northbound (lat-increasing) leg -> bearing near 0 (north),
    # not the diagonal ~45 degrees a straight chord would give.
    early_position = compute_position_at(schedule, 20.0, route_geometry=route_geometry)
    assert early_position.bearing is not None
    assert early_position.bearing == pytest.approx(0.0, abs=5.0)

    straight_line_bearing = compute_bearing(Point(0.0, 0.0), Point(1.0, 1.0))
    assert early_position.bearing != pytest.approx(straight_line_bearing, abs=5.0)
