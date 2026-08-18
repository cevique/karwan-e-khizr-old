"""
Pure unit tests for `simulation.engine` and `simulation.timing`.

No database, no FastAPI, no event loop - everything here is a plain
function/dataclass, so these run as ordinary synchronous tests, fast and
fully isolated. This is where the task's determinism requirement
("given the same initial state and elapsed time, the result should be
deterministic") is directly verified.
"""

from __future__ import annotations

import decimal
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
from simulation.geo import Point, compute_bearing, haversine_distance_m, interpolate_point
from simulation.timing import StopTimingInput, compute_stop_time_offsets

# ---------------------------------------------------------------------------
# simulation.geo
# ---------------------------------------------------------------------------


def test_haversine_distance_between_identical_points_is_zero():
    p = Point(33.6844, 73.0479)
    assert haversine_distance_m(p, p) == pytest.approx(0.0, abs=1e-6)


def test_haversine_distance_is_symmetric_and_positive():
    a = Point(33.6844, 73.0479)  # roughly Islamabad
    b = Point(33.6938, 73.0551)
    forward = haversine_distance_m(a, b)
    backward = haversine_distance_m(b, a)
    assert forward == pytest.approx(backward)
    assert forward > 0
    # These two points are a little over a kilometer apart - sanity bound,
    # not an exact assertion, since the point of this test is "roughly
    # the right order of magnitude", not pinning an exact float.
    assert 500 < forward < 2000


def test_interpolate_point_at_endpoints_and_midpoint():
    a = Point(0.0, 0.0)
    b = Point(10.0, 20.0)
    assert interpolate_point(a, b, 0.0) == a
    assert interpolate_point(a, b, 1.0) == b
    midpoint = interpolate_point(a, b, 0.5)
    assert midpoint.latitude == pytest.approx(5.0)
    assert midpoint.longitude == pytest.approx(10.0)


def test_interpolate_point_clamps_fraction_outside_zero_one():
    a = Point(0.0, 0.0)
    b = Point(10.0, 10.0)
    assert interpolate_point(a, b, -5.0) == a
    assert interpolate_point(a, b, 5.0) == b


# ---------------------------------------------------------------------------
# simulation.timing.compute_stop_time_offsets
# ---------------------------------------------------------------------------


def _stop(stop_id, lat, lon, distance_m=None):
    return StopTimingInput(
        stop_id=stop_id,
        latitude=lat,
        longitude=lon,
        distance_along_route_m=(
            decimal.Decimal(str(distance_m)) if distance_m is not None else None
        ),
    )


def test_compute_stop_time_offsets_single_stop_has_zero_offsets():
    s1 = uuid.uuid4()
    offsets = compute_stop_time_offsets([_stop(s1, 0.0, 0.0)])
    assert offsets == [(0, 0)]


def test_compute_stop_time_offsets_uses_distance_along_route_when_available():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    points = [
        _stop(s1, 0.0, 0.0, distance_m=0),
        _stop(s2, 0.0, 1.0, distance_m=1000),  # exactly 1km along the route
    ]
    offsets = compute_stop_time_offsets(points, speed_kmh=36.0, dwell_seconds=10.0)
    # 1000m at 36 km/h (=10 m/s) = 100s travel time.
    assert offsets[0].arrival_offset_s == 0
    assert offsets[0].departure_offset_s == 10  # dwell at first (non-last) stop
    assert offsets[1].arrival_offset_s == 110  # 10s dwell + 100s travel
    assert offsets[1].departure_offset_s == 110  # last stop: no further dwell


def test_compute_stop_time_offsets_falls_back_to_haversine_without_distance():
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    points = [_stop(s1, 0.0, 0.0), _stop(s2, 0.0, 0.01)]
    offsets = compute_stop_time_offsets(points)
    assert offsets[1].arrival_offset_s > offsets[0].departure_offset_s


def test_compute_stop_time_offsets_falls_back_when_distance_is_non_increasing():
    """A malformed/duplicate distance_along_route_m (not strictly
    increasing) must not produce a zero or negative segment - falls back
    to straight-line distance instead."""
    s1, s2 = uuid.uuid4(), uuid.uuid4()
    points = [
        _stop(s1, 0.0, 0.0, distance_m=500),
        _stop(s2, 0.0, 0.01, distance_m=500),  # same distance - non-increasing
    ]
    offsets = compute_stop_time_offsets(points)
    assert offsets[1].arrival_offset_s > offsets[0].departure_offset_s


def test_compute_stop_time_offsets_is_non_decreasing_across_many_stops():
    stops = [_stop(uuid.uuid4(), 0.0, i * 0.01) for i in range(6)]
    offsets = compute_stop_time_offsets(stops)
    previous_departure = -1
    for arrival, departure in offsets:
        assert arrival >= previous_departure
        assert departure >= arrival
        previous_departure = departure


def test_compute_stop_time_offsets_rejects_empty_points():
    with pytest.raises(ValueError):
        compute_stop_time_offsets([])


def test_compute_stop_time_offsets_rejects_non_positive_speed():
    with pytest.raises(ValueError):
        compute_stop_time_offsets([_stop(uuid.uuid4(), 0.0, 0.0)], speed_kmh=0)


def test_compute_stop_time_offsets_rejects_negative_dwell():
    with pytest.raises(ValueError):
        compute_stop_time_offsets(
            [_stop(uuid.uuid4(), 0.0, 0.0)], dwell_seconds=-1
        )


# ---------------------------------------------------------------------------
# simulation.engine.compute_position_at
# ---------------------------------------------------------------------------


def _schedule(*stops: ScheduleStop) -> TripSchedule:
    return TripSchedule(trip_id=uuid.uuid4(), route_id=uuid.uuid4(), stops=stops)


@pytest.fixture
def three_stop_schedule():
    s1, s2, s3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    return _schedule(
        ScheduleStop(s1, 1, 0.0, 0.0, arrival_offset_s=0, departure_offset_s=20),
        ScheduleStop(s2, 2, 0.0, 1.0, arrival_offset_s=200, departure_offset_s=220),
        ScheduleStop(s3, 3, 0.0, 2.0, arrival_offset_s=420, departure_offset_s=420),
    ), (s1, s2, s3)


def test_compute_position_at_is_deterministic_for_same_inputs(three_stop_schedule):
    schedule, _ = three_stop_schedule
    first = compute_position_at(schedule, 150.0)
    second = compute_position_at(schedule, 150.0)
    assert first == second


def test_compute_position_at_before_trip_start_is_not_started(three_stop_schedule):
    schedule, (s1, _, _) = three_stop_schedule
    position = compute_position_at(schedule, -10.0)
    assert position.status == NOT_STARTED
    assert position.current_stop_id == s1
    assert (position.latitude, position.longitude) == (0.0, 0.0)


def test_compute_position_at_exactly_at_first_stop_is_at_stop(three_stop_schedule):
    schedule, (s1, s2, _) = three_stop_schedule
    position = compute_position_at(schedule, 0.0)
    assert position.status == AT_STOP
    assert position.current_stop_id == s1
    assert position.next_stop_id == s2


def test_compute_position_at_during_dwell_window_is_at_stop(three_stop_schedule):
    schedule, (s1, s2, _) = three_stop_schedule
    position = compute_position_at(schedule, 10.0)
    assert position.status == AT_STOP
    assert position.current_stop_id == s1
    assert position.next_stop_id == s2


def test_compute_position_at_mid_segment_interpolates_linearly(three_stop_schedule):
    schedule, (s1, s2, _) = three_stop_schedule
    # Segment from s1 (departs at 20) to s2 (arrives at 200): halfway
    # through in time is elapsed_s = 20 + (200-20)/2 = 110.
    position = compute_position_at(schedule, 110.0)
    assert position.status == EN_ROUTE
    assert position.current_stop_id == s1
    assert position.next_stop_id == s2
    assert position.longitude == pytest.approx(0.5, abs=1e-6)


def test_compute_position_at_end_of_trip_is_completed(three_stop_schedule):
    schedule, (_, _, s3) = three_stop_schedule
    position = compute_position_at(schedule, 420.0)
    assert position.status == COMPLETED
    assert position.current_stop_id == s3
    assert position.next_stop_id is None


def test_compute_position_at_past_end_of_trip_stays_completed(three_stop_schedule):
    schedule, (_, _, s3) = three_stop_schedule
    position = compute_position_at(schedule, 10_000.0)
    assert position.status == COMPLETED
    assert position.current_stop_id == s3
    assert (position.latitude, position.longitude) == (0.0, 2.0)


def test_compute_position_at_carries_through_vehicle_id_and_as_of(
    three_stop_schedule,
):
    import datetime

    schedule, _ = three_stop_schedule
    vehicle_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.timezone.utc)
    position = compute_position_at(schedule, 0.0, vehicle_id=vehicle_id, as_of=now)
    assert position.vehicle_id == vehicle_id
    assert position.as_of == now


def test_compute_position_at_single_stop_schedule():
    s1 = uuid.uuid4()
    schedule = _schedule(
        ScheduleStop(s1, 1, 5.0, 5.0, arrival_offset_s=0, departure_offset_s=0)
    )
    at_start = compute_position_at(schedule, 0.0)
    assert at_start.status == AT_STOP
    after = compute_position_at(schedule, 5.0)
    assert after.status == COMPLETED


def test_compute_position_at_rejects_empty_schedule():
    empty_schedule = _schedule()
    with pytest.raises(ValueError):
        compute_position_at(empty_schedule, 0.0)


def test_compute_position_at_movement_is_monotonic_along_the_route(
    three_stop_schedule,
):
    """As elapsed_s increases, the vehicle's position never jumps
    backwards - a basic sanity property of the interpolation."""
    schedule, _ = three_stop_schedule
    previous_longitude = -1.0
    for elapsed_s in range(-10, 450, 5):
        position = compute_position_at(schedule, float(elapsed_s))
        assert position.longitude >= previous_longitude - 1e-9
        previous_longitude = position.longitude


# ---------------------------------------------------------------------------
# Phase 4: bearing / speed_kmh (plan.md section F/G)
# ---------------------------------------------------------------------------


def test_compute_position_at_not_started_bearing_faces_first_stop(
    three_stop_schedule,
):
    schedule, (s1, s2, _) = three_stop_schedule
    position = compute_position_at(schedule, -10.0)
    assert position.status == NOT_STARTED
    # s1 -> s2 is due east (same latitude, increasing longitude) -> 90 degrees.
    assert position.bearing == pytest.approx(90.0, abs=1e-6)
    assert position.speed_kmh == 0.0


def test_compute_position_at_at_stop_bearing_faces_next_stop(three_stop_schedule):
    schedule, _ = three_stop_schedule
    position = compute_position_at(schedule, 10.0)  # dwelling at s1
    assert position.status == AT_STOP
    assert position.bearing == pytest.approx(90.0, abs=1e-6)
    assert position.speed_kmh == 0.0


def test_compute_position_at_en_route_bearing_and_speed(three_stop_schedule):
    schedule, _ = three_stop_schedule
    # Mid-segment between s1 (departs 20) and s2 (arrives 200): the two
    # points are due east of each other, so bearing is 90 degrees; speed
    # is the implied constant speed for that segment (distance/duration).
    position = compute_position_at(schedule, 110.0)
    assert position.status == EN_ROUTE
    assert position.bearing == pytest.approx(90.0, abs=1e-6)
    assert position.speed_kmh is not None
    assert position.speed_kmh > 0.0
    # Same segment, same distance/duration -> the same speed at every
    # point within it (a constant-speed assumption, not a curve).
    position_later_in_segment = compute_position_at(schedule, 150.0)
    assert position_later_in_segment.speed_kmh == pytest.approx(position.speed_kmh)


def test_compute_position_at_completed_has_no_bearing_or_motion(three_stop_schedule):
    schedule, _ = three_stop_schedule
    position = compute_position_at(schedule, 420.0)
    assert position.status == COMPLETED
    assert position.bearing is None
    assert position.speed_kmh == 0.0


def test_compute_position_at_single_stop_schedule_has_no_bearing():
    """No second stop to face -> bearing is None even while `not_started`,
    not a fabricated direction."""
    s1 = uuid.uuid4()
    schedule = _schedule(
        ScheduleStop(s1, 1, 5.0, 5.0, arrival_offset_s=0, departure_offset_s=0)
    )
    at_start = compute_position_at(schedule, -5.0)
    assert at_start.bearing is None
    assert at_start.speed_kmh == 0.0


def test_compute_position_at_bearing_is_normalized_degrees(three_stop_schedule):
    schedule, _ = three_stop_schedule
    for elapsed_s in (-10.0, 0.0, 10.0, 110.0, 210.0, 420.0, 1000.0):
        position = compute_position_at(schedule, elapsed_s)
        if position.bearing is not None:
            assert 0.0 <= position.bearing < 360.0


# ---------------------------------------------------------------------------
# Phase 4: compute_bearing (simulation.geo)
# ---------------------------------------------------------------------------


def test_compute_bearing_due_north_is_zero():
    a = Point(0.0, 0.0)
    b = Point(1.0, 0.0)
    assert compute_bearing(a, b) == pytest.approx(0.0, abs=1e-6)


def test_compute_bearing_due_east_is_ninety():
    a = Point(0.0, 0.0)
    b = Point(0.0, 1.0)
    assert compute_bearing(a, b) == pytest.approx(90.0, abs=1e-6)


def test_compute_bearing_due_south_is_180():
    a = Point(1.0, 0.0)
    b = Point(0.0, 0.0)
    assert compute_bearing(a, b) == pytest.approx(180.0, abs=1e-6)


def test_compute_bearing_due_west_is_270():
    a = Point(0.0, 1.0)
    b = Point(0.0, 0.0)
    assert compute_bearing(a, b) == pytest.approx(270.0, abs=1e-6)


def test_compute_bearing_identical_points_is_defined_not_raising():
    p = Point(33.6844, 73.0479)
    # Degenerate but must not raise - see compute_bearing's docstring.
    assert compute_bearing(p, p) == pytest.approx(0.0, abs=1e-6)
