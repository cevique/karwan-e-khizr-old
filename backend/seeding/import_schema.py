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

Shape (four flat lists, all cross-referenced by string `ref`, never by
database ID - refs are meaningful only within one import and are never
persisted):

    agencies:    [{name, network_type?}]
    stops:       [{ref, name, latitude, longitude}]
    routes:      [{ref, agency, short_name, long_name?, color?}]
    route_stops: [{route_ref, stop_ref, sequence, distance_along_route_m?}]

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
    latitude: float
    longitude: float


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
