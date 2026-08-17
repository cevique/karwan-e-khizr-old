"""
The normalized, source-agnostic shape that both JSON and CSV input get
parsed into (`seeding.parsers`) before validation (`seeding.validation`)
and persistence (`seeding.importer`).

Deliberately plain dataclasses, not `db.models` ORM classes and not
Pydantic models: this is an in-memory intermediate representation with no
database or HTTP dependency, shared unchanged between "validate a payload
without persisting it" (the dev API's dry-run endpoint) and "actually
persist it" (the admin API's import endpoint) - both build one of these,
then call into `validation`/`importer` identically.

Shape (four flat lists plus optional timetable data, all cross-referenced
by string `ref`, never by database ID - refs are meaningful only within
one import and are never persisted):

    agencies:    [{name, network_type?}]
    stops:       [{ref, name, latitude?, longitude?}]
    routes:      [{ref, agency, short_name, long_name?, color?}]
    route_stops: [{route_ref, stop_ref, sequence, distance_along_route_m?}]
    trip_patterns: [{route_ref, direction, headway_minutes,
                     total_trips_per_day, first_trip_start,
                     last_trip_start?, source_pdf?, confidence}]
    trip_stop_times: {(route_ref, direction): [ImportStopTime...]}

`ImportStop.latitude`/`longitude` are optional because the canonical
`transit_data.json` dataset deliberately leaves them `null` for stops
whose coordinates are not established (they are filled by a later
geospatial-enrichment pass, not fabricated at import time) - see
`docs/transit_data.json` and `plan.md` section B.

`ImportStop.confidence` carries the source dataset's own confidence
rating for a stop that DOES have coordinates (`"APPROXIMATE"` for all 17
of `transit_data.json`'s located stops today). `seeding.importer` copies
it onto `Stop.coordinate_source`/`coordinate_confidence` only when
creating a stop that has a location - see `plan.md` section C and
`seeding.geocoding` for how the remaining null-coordinate stops get
their provenance filled in later (Phase 2).

A route's `agency` field is an agency *name* (matched case-sensitively
against `agencies[].name`, or auto-created if not listed there - see
`importer.py`), not a `ref` into the agencies list - agencies don't need
a separate ref namespace since `Agency.name` is already the column this
project enforces uniqueness on (see `db/models/agency.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ImportAgency:
    name: str
    network_type: str | None = None


@dataclass(frozen=True)
class ImportStop:
    ref: str
    name: str
    latitude: float | None = None
    longitude: float | None = None
    confidence: str | None = None


@dataclass(frozen=True)
class ImportTripPattern:
    """A canonical trip pattern: one direction of one route, with the
    headway metadata needed to expand it into a full day's real `Trip`
    rows (see `plan.md` section E and `docs/SIMULATION_DATA_SPEC.md`).

    Each pattern corresponds to one entry in `transit_data.json`'s `trips`
    array - a real, officially-published per-route/direction stop-time
    pattern from a CDA timetable PDF. The importer generates
    `total_trips_per_day` `Trip` rows whose `scheduled_start_time` =
    `first_trip_start` + n x `headway_minutes` (n = 0..N-1, capped so the
    last generated start does not exceed `last_trip_start` where given),
    and copies the pattern's `ImportStopTime` offsets verbatim onto each.
    """

    route_ref: str
    direction: str  # "forward" | "backward"
    headway_minutes: float
    total_trips_per_day: int
    first_trip_start: str  # "HH:MM:SS"
    last_trip_start: str | None = None  # "HH:MM:SS" or null
    source_pdf: str | None = None
    confidence: str = "UNKNOWN"


@dataclass(frozen=True)
class ImportStopTime:
    """One stop's arrival/departure offsets within a canonical trip
    pattern, both as seconds after `Trip.scheduled_start_time`."""

    stop_ref: str
    sequence: int
    arrival_offset_s: int
    departure_offset_s: int


@dataclass(frozen=True)
class ImportRoute:
    ref: str
    agency: str
    short_name: str
    long_name: str | None = None
    color: str | None = None


@dataclass(frozen=True)
class ImportRouteStop:
    route_ref: str
    stop_ref: str
    sequence: int
    distance_along_route_m: float | None = None


@dataclass(frozen=True)
class ImportDataset:
    agencies: tuple[ImportAgency, ...] = field(default_factory=tuple)
    stops: tuple[ImportStop, ...] = field(default_factory=tuple)
    routes: tuple[ImportRoute, ...] = field(default_factory=tuple)
    route_stops: tuple[ImportRouteStop, ...] = field(default_factory=tuple)
    trip_patterns: tuple[ImportTripPattern, ...] = field(default_factory=tuple)
    # stop_times keyed by (route_ref, direction) -> tuple of ImportStopTime
    trip_stop_times: dict[tuple[str, str], tuple[ImportStopTime, ...]] = field(
        default_factory=dict
    )

    def routes_with_stops(self) -> dict[str, list[ImportRouteStop]]:
        """Group `route_stops` by `route_ref`, each group sorted by
        `sequence` - the shape both validation and the importer actually
        want to iterate, computed once instead of twice."""
        grouped: dict[str, list[ImportRouteStop]] = {}
        for rs in self.route_stops:
            grouped.setdefault(rs.route_ref, []).append(rs)
        for group in grouped.values():
            group.sort(key=lambda rs: rs.sequence)
        return grouped

    def stop_times_for(self, route_ref: str, direction: str) -> tuple[ImportStopTime, ...]:
        """The canonical stop-time pattern for one route/direction, or an
        empty tuple if this dataset carries no pattern for it."""
        return self.trip_stop_times.get((route_ref, direction), ())
