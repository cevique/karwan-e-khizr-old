"""
Validation logic for transit data, kept deliberately separate from
`seeding.importer` (which persists) and `seeding.parsers` (which parses
raw JSON/CSV into an `ImportDataset`) so it can be:

- run as a dry-run "validate only, don't persist" operation (the dev
  API's `/dev/validate` endpoint), and
- run again, unconditionally, as the first step of every real import
  (`seeding.importer.import_dataset`) before anything is written - an
  import with any error-level issue is rejected in full, never applied
  partially.

Pure and side-effect-free: every function here takes an `ImportDataset`
(or a single record) and returns data: no database session, no I/O.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from seeding.import_schema import ImportDataset

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    # Best-effort pointer to where the issue is, e.g. "stops[3]",
    # "routes[blue_line]", "route_stops[blue_line]" - not a machine-parsed
    # path, just enough for a human (or an API error response) to find it.
    location: str


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...]

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == "warning")

    @property
    def is_valid(self) -> bool:
        """True iff there are no error-level issues. Warnings alone never
        block an import - only errors do (see `importer.import_dataset`)."""
        return len(self.errors) == 0


MIN_STOPS_PER_ROUTE = 2


def _valid_coordinate(latitude: float | None, longitude: float | None) -> bool:
    """A coordinate pair is valid iff it is either fully absent (both
    `None` - a stop whose location is simply not known yet, allowed since
    `Stop.location` is nullable) or both present and in-range. A pair with
    exactly one `None` is invalid."""
    if latitude is None and longitude is None:
        return True
    if latitude is None or longitude is None:
        return False
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return False
    return -90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0


def _valid_time(value: str) -> bool:
    """Validate an "HH:MM:SS" clock time (24h). Returns False for values
    that don't parse, so the caller can attach a location."""
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
    except (ValueError, AttributeError):
        return False
    return 0 <= hours <= 23 and 0 <= minutes <= 59 and 0 <= seconds <= 59


def validate_dataset(
    dataset: ImportDataset,
    *,
    allow_routes_without_stops: bool = False,
) -> ValidationResult:
    """Validate a complete `ImportDataset`, self-contained (no database
    lookups - every reference must resolve within `dataset` itself).

    `allow_routes_without_stops=True` downgrades the `insufficient_stops`
    error to a warning for routes that have no (or too few) route_stops
    rows. The generic import pipeline (admin JSON/CSV upload, seeded demo
    data) keeps the strict default; the canonical `transit_data.json`
    importer passes `True` because 21 of its 26 routes intentionally have
    no stop sequence yet (documented in DATA_GAPS.md) and must still be
    importable as Route rows.

    Checks performed (see this module's and the task's requirements):

    - duplicate identifiers: duplicate agency names, duplicate stop refs,
      duplicate route refs
    - invalid coordinates / invalid geometry: non-finite or out-of-range
      latitude/longitude on any stop (null/null is allowed - see
      `_valid_coordinate`)
    - missing route/stop references: a `route_stops` row naming a
      `route_ref`/`stop_ref` not present in `routes`/`stops`, or a route
      naming a blank agency
    - duplicate route-stop sequence: two `route_stops` rows for the same
      route claiming the same `sequence`
    - invalid sequence ordering: a non-positive/non-integer sequence, or
      (as a warning, not an error - the schema only requires monotonic,
      not contiguous, per `db/models/route_stop.py`) a route whose
      sequences have gaps
    - routes with insufficient stops: fewer than `MIN_STOPS_PER_ROUTE`
      valid route_stops rows, which can never contribute a ride edge
      (downgraded to a warning when `allow_routes_without_stops` is set)
    - trip patterns: every pattern references an existing route and every
      stop_time references an existing stop, offsets are non-decreasing
      and non-negative with the first arrival at 0s, headway and trip
      counts are positive, and `last_trip_start` (when given) is not
      earlier than `first_trip_start` and is consistent with the headway
    """
    issues: list[ValidationIssue] = []

    # --- duplicate identifiers ---------------------------------------
    seen_agency_names: set[str] = set()
    for i, agency in enumerate(dataset.agencies):
        if not agency.name or not agency.name.strip():
            issues.append(
                ValidationIssue(
                    "error", "agency_name_blank", "Agency name is blank.",
                    f"agencies[{i}]",
                )
            )
            continue
        if agency.name in seen_agency_names:
            issues.append(
                ValidationIssue(
                    "error",
                    "duplicate_agency_name",
                    f"Agency name {agency.name!r} appears more than once.",
                    f"agencies[{i}]",
                )
            )
        seen_agency_names.add(agency.name)

    seen_stop_refs: set[str] = set()
    stop_refs: set[str] = set()
    for i, stop in enumerate(dataset.stops):
        if not stop.ref or not stop.ref.strip():
            issues.append(
                ValidationIssue(
                    "error", "stop_ref_blank", "Stop ref is blank.", f"stops[{i}]"
                )
            )
            continue
        if stop.ref in seen_stop_refs:
            issues.append(
                ValidationIssue(
                    "error",
                    "duplicate_stop_ref",
                    f"Stop ref {stop.ref!r} appears more than once.",
                    f"stops[{i}]",
                )
            )
        seen_stop_refs.add(stop.ref)
        stop_refs.add(stop.ref)

        if not _valid_coordinate(stop.latitude, stop.longitude):
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_coordinates",
                    f"Stop {stop.ref!r} has invalid coordinates "
                    f"(latitude={stop.latitude!r}, longitude={stop.longitude!r}); "
                    "latitude must be within [-90, 90] and longitude within "
                    "[-180, 180].",
                    f"stops[{i}]",
                )
            )

    seen_route_refs: set[str] = set()
    route_refs: set[str] = set()
    route_ref_to_agency: dict[str, str] = {}
    for i, route in enumerate(dataset.routes):
        if not route.ref or not route.ref.strip():
            issues.append(
                ValidationIssue(
                    "error", "route_ref_blank", "Route ref is blank.", f"routes[{i}]"
                )
            )
            continue
        if route.ref in seen_route_refs:
            issues.append(
                ValidationIssue(
                    "error",
                    "duplicate_route_ref",
                    f"Route ref {route.ref!r} appears more than once.",
                    f"routes[{i}]",
                )
            )
        seen_route_refs.add(route.ref)
        route_refs.add(route.ref)
        route_ref_to_agency[route.ref] = route.agency

        if not route.short_name or not route.short_name.strip():
            issues.append(
                ValidationIssue(
                    "error",
                    "route_short_name_blank",
                    f"Route {route.ref!r} has a blank short_name.",
                    f"routes[{i}]",
                )
            )
        if not route.agency or not route.agency.strip():
            issues.append(
                ValidationIssue(
                    "error",
                    "route_agency_blank",
                    f"Route {route.ref!r} has a blank agency.",
                    f"routes[{i}]",
                )
            )

    # --- missing route/stop references + per-route sequence checks ---
    grouped = dataset.routes_with_stops()

    for route_ref, route_stops in grouped.items():
        location = f"route_stops[{route_ref}]"

        if route_ref not in route_refs:
            issues.append(
                ValidationIssue(
                    "error",
                    "missing_route_reference",
                    f"route_stops reference route_ref {route_ref!r}, which "
                    "is not defined in routes.",
                    location,
                )
            )

        seen_sequences: dict[int, int] = {}
        valid_row_count = 0
        for rs in route_stops:
            row_valid = True

            if rs.stop_ref not in stop_refs:
                issues.append(
                    ValidationIssue(
                        "error",
                        "missing_stop_reference",
                        f"route_stops row for route {route_ref!r} references "
                        f"stop_ref {rs.stop_ref!r}, which is not defined in "
                        "stops.",
                        location,
                    )
                )
                row_valid = False

            if not isinstance(rs.sequence, int) or rs.sequence < 1:
                issues.append(
                    ValidationIssue(
                        "error",
                        "invalid_sequence_ordering",
                        f"route_stops row for route {route_ref!r}, stop "
                        f"{rs.stop_ref!r} has an invalid sequence "
                        f"({rs.sequence!r}); sequence must be a positive "
                        "integer.",
                        location,
                    )
                )
                row_valid = False
            else:
                seen_sequences[rs.sequence] = seen_sequences.get(rs.sequence, 0) + 1

            if row_valid:
                valid_row_count += 1

        for sequence, count in seen_sequences.items():
            if count > 1:
                issues.append(
                    ValidationIssue(
                        "error",
                        "duplicate_route_stop_sequence",
                        f"Route {route_ref!r} has {count} stops claiming "
                        f"sequence {sequence}.",
                        location,
                    )
                )

        sorted_sequences = sorted(seen_sequences)
        if sorted_sequences and sorted_sequences != list(
            range(sorted_sequences[0], sorted_sequences[0] + len(sorted_sequences))
        ):
            issues.append(
                ValidationIssue(
                    "warning",
                    "non_contiguous_sequence",
                    f"Route {route_ref!r}'s stop sequence has gaps: "
                    f"{sorted_sequences}. Not an error (RouteStop.sequence "
                    "only needs to be monotonic, per db/models/route_stop.py), "
                    "but usually indicates a missing stop.",
                    location,
                )
            )

        if valid_row_count < MIN_STOPS_PER_ROUTE:
            severity: Severity = "error"
            if allow_routes_without_stops:
                severity = "warning"
            issues.append(
                ValidationIssue(
                    severity,
                    "insufficient_stops",
                    f"Route {route_ref!r} has only {valid_row_count} valid "
                    f"stop(s); at least {MIN_STOPS_PER_ROUTE} are required "
                    "to form a ride edge.",
                    f"routes[{route_ref}]",
                )
            )

    # A route defined in `routes` with no route_stops rows at all - the
    # loop above only catches routes that have *some* route_stops rows.
    for route_ref in route_refs - set(grouped):
        severity: Severity = "error"
        if allow_routes_without_stops:
            severity = "warning"
        issues.append(
            ValidationIssue(
                severity,
                "insufficient_stops",
                f"Route {route_ref!r} has no stops at all; at least "
                f"{MIN_STOPS_PER_ROUTE} are required to form a ride edge.",
                f"routes[{route_ref}]",
            )
        )

    # --- trip patterns -------------------------------------------------
    seen_patterns: set[tuple[str, str]] = set()
    for i, pattern in enumerate(dataset.trip_patterns):
        location = f"trip_patterns[{i}]"

        if pattern.route_ref not in route_refs:
            issues.append(
                ValidationIssue(
                    "error",
                    "missing_route_reference",
                    f"trip pattern references route_ref {pattern.route_ref!r}, "
                    "which is not defined in routes.",
                    location,
                )
            )

        direction = pattern.direction.lower()
        if direction not in ("forward", "backward"):
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_direction",
                    f"trip pattern for route {pattern.route_ref!r} has an "
                    f"invalid direction {pattern.direction!r}; must be "
                    "'forward' or 'backward'.",
                    location,
                )
            )

        if (pattern.route_ref, direction) in seen_patterns:
            issues.append(
                ValidationIssue(
                    "error",
                    "duplicate_trip_pattern",
                    f"Multiple trip patterns for route {pattern.route_ref!r} "
                    f"direction {direction!r}.",
                    location,
                )
            )
        seen_patterns.add((pattern.route_ref, direction))

        if pattern.headway_minutes <= 0:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_headway",
                    f"trip pattern for route {pattern.route_ref!r} has a "
                    f"non-positive headway ({pattern.headway_minutes} minutes).",
                    location,
                )
            )
        if pattern.total_trips_per_day <= 0:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_trip_count",
                    f"trip pattern for route {pattern.route_ref!r} has a "
                    f"non-positive total_trips_per_day "
                    f"({pattern.total_trips_per_day}).",
                    location,
                )
            )
        if not _valid_time(pattern.first_trip_start):
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_time",
                    f"trip pattern for route {pattern.route_ref!r} has an "
                    f"invalid first_trip_start {pattern.first_trip_start!r}; "
                    "expected HH:MM:SS.",
                    location,
                )
            )
        if pattern.last_trip_start is not None and not _valid_time(
            pattern.last_trip_start
        ):
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_time",
                    f"trip pattern for route {pattern.route_ref!r} has an "
                    f"invalid last_trip_start {pattern.last_trip_start!r}; "
                    "expected HH:MM:SS.",
                    location,
                )
            )

        stop_times = dataset.stop_times_for(pattern.route_ref, direction)
        if not stop_times:
            issues.append(
                ValidationIssue(
                    "error",
                    "missing_stop_times",
                    f"trip pattern for route {pattern.route_ref!r} direction "
                    f"{direction!r} has no stop_times.",
                    location,
                )
            )
        else:
            issues.extend(_validate_stop_times(dataset, stop_times, location))

        # Consistency between the headway, the two clock times, and the
        # trip count: the last generated trip should not start after
        # last_trip_start when it is given. Only checked when the clock
        # times parse (otherwise the parse error above already reports it).
        if (
            pattern.last_trip_start is not None
            and _valid_time(pattern.first_trip_start)
            and _valid_time(pattern.last_trip_start)
            and pattern.total_trips_per_day > 0
            and pattern.headway_minutes > 0
        ):
            last_start_s = _time_to_seconds(pattern.last_trip_start)
            generated_last_s = _time_to_seconds(
                pattern.first_trip_start
            ) + (pattern.total_trips_per_day - 1) * pattern.headway_minutes * 60
            if generated_last_s > last_start_s:
                issues.append(
                    ValidationIssue(
                        "warning",
                        "trip_count_exceeds_last_trip_start",
                        f"trip pattern for route {pattern.route_ref!r}: "
                        f"{pattern.total_trips_per_day} trips at "
                        f"{pattern.headway_minutes}-minute headway from "
                        f"{pattern.first_trip_start} would start later than "
                        f"the stated last_trip_start "
                        f"({pattern.last_trip_start}).",
                        location,
                    )
                )

    return ValidationResult(issues=tuple(issues))


def _time_to_seconds(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _validate_stop_times(
    dataset: ImportDataset,
    stop_times: tuple,
    location: str,
) -> list[ValidationIssue]:
    """Validate one pattern's stop_times: every stop_ref must exist, every
    offset must be non-negative and non-decreasing, the first arrival must
    be 0s, and (as a warning) the last stop's arrival/departure should
    agree. Returns the list of issues found; the caller appends them to
    the dataset-wide list."""
    issues: list[ValidationIssue] = []
    stop_refs = {s.ref for s in dataset.stops}
    prev_offset = -1
    for j, st in enumerate(stop_times):
        st_location = f"{location}.stop_times[{j}]"
        if st.stop_ref not in stop_refs:
            issues.append(
                ValidationIssue(
                    "error",
                    "missing_stop_reference",
                    f"stop_time references stop_ref {st.stop_ref!r}, which "
                    "is not defined in stops.",
                    st_location,
                )
            )
        if not isinstance(st.sequence, int) or st.sequence < 1:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_sequence_ordering",
                    f"stop_time for stop {st.stop_ref!r} has an invalid "
                    f"sequence ({st.sequence!r}); sequence must be a "
                    "positive integer.",
                    st_location,
                )
            )
        if st.arrival_offset_s < 0:
            issues.append(
                ValidationIssue(
                    "error",
                    "negative_offset",
                    f"stop_time for stop {st.stop_ref!r} has a negative "
                    f"arrival offset ({st.arrival_offset_s}s).",
                    st_location,
                )
            )
        if st.departure_offset_s < 0:
            issues.append(
                ValidationIssue(
                    "error",
                    "negative_offset",
                    f"stop_time for stop {st.stop_ref!r} has a negative "
                    f"departure offset ({st.departure_offset_s}s).",
                    st_location,
                )
            )
        if st.departure_offset_s < st.arrival_offset_s:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_offset_ordering",
                    f"stop_time for stop {st.stop_ref!r} departs "
                    f"({st.departure_offset_s}s) before it arrives "
                    f"({st.arrival_offset_s}s).",
                    st_location,
                )
            )
        if st.arrival_offset_s < prev_offset:
            issues.append(
                ValidationIssue(
                    "error",
                    "invalid_offset_ordering",
                    f"stop_time for stop {st.stop_ref!r} has arrival offset "
                    f"{st.arrival_offset_s}s, which is earlier than the "
                    "previous stop's offset.",
                    st_location,
                )
            )
        prev_offset = max(prev_offset, st.arrival_offset_s)

    if stop_times and stop_times[0].arrival_offset_s != 0:
        issues.append(
            ValidationIssue(
                "error",
                "first_offset_not_zero",
                f"The first stop_time of the pattern has arrival offset "
                f"{stop_times[0].arrival_offset_s}s; the first stop must "
                "arrive at 0s.",
                location,
            )
        )
    if len(stop_times) > 1:
        last = stop_times[-1]
        if last.arrival_offset_s != last.departure_offset_s:
            issues.append(
                ValidationIssue(
                    "warning",
                    "last_stop_dwell",
                    f"The last stop_time of the pattern arrives at "
                    f"{last.arrival_offset_s}s but departs at "
                    f"{last.departure_offset_s}s; a terminal stop should "
                    "have no dwell time.",
                    location,
                )
            )

    return issues
