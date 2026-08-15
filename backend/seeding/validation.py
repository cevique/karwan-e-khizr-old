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


def _valid_coordinate(latitude: float, longitude: float) -> bool:
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return False
    return -90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0


def validate_dataset(dataset: ImportDataset) -> ValidationResult:
    """Validate a complete `ImportDataset`, self-contained (no database
    lookups - every reference must resolve within `dataset` itself).

    Checks performed (see this module's and the task's requirements):

    - duplicate identifiers: duplicate agency names, duplicate stop refs,
      duplicate route refs
    - invalid coordinates / invalid geometry: non-finite or out-of-range
      latitude/longitude on any stop
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
            issues.append(
                ValidationIssue(
                    "error",
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
        issues.append(
            ValidationIssue(
                "error",
                "insufficient_stops",
                f"Route {route_ref!r} has no stops at all; at least "
                f"{MIN_STOPS_PER_ROUTE} are required to form a ride edge.",
                f"routes[{route_ref}]",
            )
        )

    return ValidationResult(issues=tuple(issues))
