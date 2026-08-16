"""
Parse raw JSON or CSV input into a normalized `ImportDataset`
(`seeding.import_schema`).

All source-format-specific knowledge lives here and nowhere else in this
package - `seeding.validation` and `seeding.importer` only ever see an
`ImportDataset`, never raw JSON/CSV. This is what "keep
external-data-specific parsing separate from database persistence" (the
task's Import requirement) means concretely.

Both formats describe the same four tables (`agencies`, `stops`, `routes`,
`route_stops` - see `import_schema.py`'s module docstring for the exact
field names) - JSON as one nested-ish document with four top-level arrays,
CSV as four separate files/strings with a header row each.

JSON input may additionally carry an optional `trip_patterns` array - the
canonical stop-time pattern shape from `plan.md` section B (one direction
of one route plus the headway metadata to expand it into a full day's
`Trip` rows). Each entry's `stop_times` sub-array becomes the
`ImportDataset.trip_stop_times` entry keyed by `(route_ref, direction)`.
This is additive: a document with no `trip_patterns` parses exactly as
before, and the dedicated `transit_data_importer` (the canonical
`transit_data.json` -> `ImportDataset` converter) builds the same
`ImportDataset` shape without going through this generic parser.

Parse errors here are strictly about *shape* (invalid JSON syntax, a
missing required column/key, a value that can't be coerced to the
expected type) - raised as `ImportParseError`. Business-level problems
with otherwise well-formed data (a route with no stops, a duplicate ref,
an out-of-range coordinate) are NOT raised here - they're reported by
`seeding.validation.validate_dataset` on the successfully-parsed
`ImportDataset`, so a caller always gets the FULL list of problems at
once rather than stopping at the first one.
"""

from __future__ import annotations

import csv
import io
import json

from seeding.import_schema import (
    ImportAgency,
    ImportDataset,
    ImportRoute,
    ImportRouteStop,
    ImportStop,
    ImportStopTime,
    ImportTripPattern,
)


class ImportParseError(Exception):
    """Raised when raw input can't be parsed into an `ImportDataset` at
    all - malformed JSON/CSV, a missing required column/key, or a value
    that can't be coerced to the type its field needs. Distinct from a
    `ValidationResult` with errors (see module docstring): this exception
    means parsing itself failed, not that the parsed data is invalid."""


def _require_str(record: dict, key: str, *, where: str) -> str:
    value = record.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ImportParseError(f"{where}: missing required field {key!r}.")
    if not isinstance(value, str):
        raise ImportParseError(
            f"{where}: field {key!r} must be a string, got {type(value).__name__}."
        )
    return value


def _optional_str(record: dict, key: str) -> str | None:
    value = record.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _require_float(record: dict, key: str, *, where: str) -> float:
    value = record.get(key)
    if value is None or value == "":
        raise ImportParseError(f"{where}: missing required field {key!r}.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ImportParseError(
            f"{where}: field {key!r} must be a number, got {value!r}."
        ) from exc


def _require_int(record: dict, key: str, *, where: str) -> int:
    value = record.get(key)
    if value is None or value == "":
        raise ImportParseError(f"{where}: missing required field {key!r}.")
    try:
        # Reject "1.5" as a sequence number, but accept "1" and 1/1.0.
        if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
            raise ValueError(value)
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ImportParseError(
            f"{where}: field {key!r} must be an integer, got {value!r}."
        ) from exc


def _parse_trip_patterns(trip_patterns: list[dict]) -> tuple:
    """Parse the optional `trip_patterns` array into
    `(tuple[ImportTripPattern], dict[(route_ref, direction), tuple[ImportStopTime]])`.
    Each entry:

        {
          "route_ref": "fr_04",
          "direction": "forward",
          "headway_minutes": 10,
          "total_trips_per_day": 97,
          "first_trip_start": "06:00:00",
          "last_trip_start": "22:00:00",
          "source_pdf": "https://...",
          "confidence": "OFFICIAL",
          "stop_times": [
            {"stop_ref": "cda_pims_hospital", "sequence": 1,
             "arrival_offset_s": 0, "departure_offset_s": 0},
            ...
          ]
        }
    """
    patterns: list[ImportTripPattern] = []
    stop_times_by_pattern: dict[tuple[str, str], tuple[ImportStopTime, ...]] = {}

    for i, pattern in enumerate(trip_patterns):
        where = f"trip_patterns[{i}]"
        if not isinstance(pattern, dict):
            raise ImportParseError(f"{where} must be an object.")
        route_ref = _require_str(pattern, "route_ref", where=where)
        direction = _require_str(pattern, "direction", where=where)
        headway = _require_float(pattern, "headway_minutes", where=where)
        total = _require_int(pattern, "total_trips_per_day", where=where)
        first = _require_str(pattern, "first_trip_start", where=where)
        last = _optional_str(pattern, "last_trip_start")
        source_pdf = _optional_str(pattern, "source_pdf")
        confidence = _optional_str(pattern, "confidence") or "UNKNOWN"

        patterns.append(
            ImportTripPattern(
                route_ref=route_ref,
                direction=direction,
                headway_minutes=headway,
                total_trips_per_day=total,
                first_trip_start=first,
                last_trip_start=last,
                source_pdf=source_pdf,
                confidence=confidence,
            )
        )

        stop_times_raw = pattern.get("stop_times", [])
        if not isinstance(stop_times_raw, list):
            raise ImportParseError(
                f"{where}: field 'stop_times' must be a list, got "
                f"{type(stop_times_raw).__name__}."
            )
        stop_times = tuple(
            ImportStopTime(
                stop_ref=_require_str(st, "stop_ref", where=f"{where}.stop_times[{j}]"),
                sequence=_require_int(st, "sequence", where=f"{where}.stop_times[{j}]"),
                arrival_offset_s=_require_int(
                    st, "arrival_offset_s", where=f"{where}.stop_times[{j}]"
                ),
                departure_offset_s=_require_int(
                    st, "departure_offset_s", where=f"{where}.stop_times[{j}]"
                ),
            )
            for j, st in enumerate(stop_times_raw)
        )
        stop_times_by_pattern[(route_ref, direction)] = stop_times

    return tuple(patterns), stop_times_by_pattern


def _optional_float(record: dict, key: str) -> float | None:
    value = record.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ImportParseError(
            f"field {key!r} must be a number, got {value!r}."
        ) from exc


def _records_to_dataset(
    agencies: list[dict],
    stops: list[dict],
    routes: list[dict],
    route_stops: list[dict],
    trip_patterns: list[dict] | None = None,
) -> ImportDataset:
    """Shared normalization step for both JSON and CSV input, once each
    has reduced its own format down to plain lists of dicts."""
    parsed_agencies = tuple(
        ImportAgency(
            name=_require_str(a, "name", where=f"agencies[{i}]"),
            network_type=_optional_str(a, "network_type"),
        )
        for i, a in enumerate(agencies)
    )
    parsed_stops = tuple(
        ImportStop(
            ref=_require_str(s, "ref", where=f"stops[{i}]"),
            name=_require_str(s, "name", where=f"stops[{i}]"),
            latitude=_require_float(s, "latitude", where=f"stops[{i}]"),
            longitude=_require_float(s, "longitude", where=f"stops[{i}]"),
        )
        for i, s in enumerate(stops)
    )
    parsed_routes = tuple(
        ImportRoute(
            ref=_require_str(r, "ref", where=f"routes[{i}]"),
            agency=_require_str(r, "agency", where=f"routes[{i}]"),
            short_name=_require_str(r, "short_name", where=f"routes[{i}]"),
            long_name=_optional_str(r, "long_name"),
            color=_optional_str(r, "color"),
        )
        for i, r in enumerate(routes)
    )
    parsed_route_stops = tuple(
        ImportRouteStop(
            route_ref=_require_str(rs, "route_ref", where=f"route_stops[{i}]"),
            stop_ref=_require_str(rs, "stop_ref", where=f"route_stops[{i}]"),
            sequence=_require_int(rs, "sequence", where=f"route_stops[{i}]"),
            distance_along_route_m=_optional_float(rs, "distance_along_route_m"),
        )
        for i, rs in enumerate(route_stops)
    )
    parsed_trip_patterns, parsed_stop_times = _parse_trip_patterns(
        trip_patterns or []
    )
    return ImportDataset(
        agencies=parsed_agencies,
        stops=parsed_stops,
        routes=parsed_routes,
        route_stops=parsed_route_stops,
        trip_patterns=parsed_trip_patterns,
        trip_stop_times=parsed_stop_times,
    )


def parse_json_dataset(document: dict) -> ImportDataset:
    """Parse an already-decoded JSON document (a plain `dict`) into an
    `ImportDataset`. Expected shape:

        {
          "agencies": [{"name": "...", "network_type": "..."}],
          "stops": [{"ref": "...", "name": "...", "latitude": .., "longitude": ..}],
          "routes": [{"ref": "...", "agency": "...", "short_name": "...",
                       "long_name": "...", "color": "#RRGGBB"}],
          "route_stops": [{"route_ref": "...", "stop_ref": "...",
                             "sequence": 1, "distance_along_route_m": ..}],
          "trip_patterns": [{"route_ref": "...", "direction": "...",
                             "headway_minutes": .., "total_trips_per_day": ..,
                             "first_trip_start": "HH:MM:SS",
                             "last_trip_start": "HH:MM:SS",
                             "stop_times": [{"stop_ref": "...", "sequence": 1,
                                             "arrival_offset_s": 0,
                                             "departure_offset_s": 0}]}]
        }

    Every top-level key is optional (defaults to an empty list) - a
    document with only `agencies` and `stops`, for instance, is valid
    JSON *input* (whether it's a valid *dataset* - e.g. whether every
    route has enough stops - is `validation.validate_dataset`'s job, not
    this function's).
    """
    if not isinstance(document, dict):
        raise ImportParseError(
            f"Top-level JSON document must be an object, got {type(document).__name__}."
        )
    for key in ("agencies", "stops", "routes", "route_stops", "trip_patterns"):
        if key in document and not isinstance(document[key], list):
            raise ImportParseError(
                f"{key!r} must be a list, got {type(document[key]).__name__}."
            )
    return _records_to_dataset(
        agencies=document.get("agencies", []),
        stops=document.get("stops", []),
        routes=document.get("routes", []),
        route_stops=document.get("route_stops", []),
        trip_patterns=document.get("trip_patterns", []),
    )


def parse_json_text(text: str) -> ImportDataset:
    """Parse raw JSON text (e.g. an HTTP request body) into an
    `ImportDataset`. Raises `ImportParseError` on invalid JSON syntax."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportParseError(f"Invalid JSON: {exc}") from exc
    return parse_json_dataset(document)


def _read_csv_rows(text: str, *, filename: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    rows = []
    for row in reader:
        # DictReader puts unmatched extra columns under the None key and
        # leaves missing trailing columns as None - neither is a shape
        # this importer accepts silently.
        if None in row:
            raise ImportParseError(
                f"{filename}: row has more columns than the header "
                f"({reader.fieldnames})."
            )
        rows.append(row)
    return rows


def parse_csv_dataset(
    *,
    agencies_csv: str = "",
    stops_csv: str = "",
    routes_csv: str = "",
    route_stops_csv: str = "",
) -> ImportDataset:
    """Parse four CSV files (each already read into a string; any of them
    may be an empty string for "no rows of this kind") into an
    `ImportDataset`. Expected header rows:

        agencies.csv:     name, network_type
        stops.csv:        ref, name, latitude, longitude
        routes.csv:        ref, agency, short_name, long_name, color
        route_stops.csv:  route_ref, stop_ref, sequence, distance_along_route_m

    `network_type`, `long_name`, `color`, and `distance_along_route_m`
    are optional columns/values; every other column is required on every
    row of its file.
    """
    return _records_to_dataset(
        agencies=_read_csv_rows(agencies_csv, filename="agencies.csv"),
        stops=_read_csv_rows(stops_csv, filename="stops.csv"),
        routes=_read_csv_rows(routes_csv, filename="routes.csv"),
        route_stops=_read_csv_rows(route_stops_csv, filename="route_stops.csv"),
    )
