"""
Dedicated converter for the canonical `docs/transit_data.json` research
dataset into the generic `ImportDataset` shape (`seeding.import_schema`)
that `seeding.validation` and `seeding.importer` consume.

Why a separate module and not the generic `seeding.parsers.parse_json_dataset`:
`transit_data.json` is the *research* shape (uuid `id`s + human `key`s,
`operators` not `agencies`, trips carrying their own stop sequences), not
the admin-import payload shape the generic parser knows. Keeping the
mapping here means the canonical dataset never gets squeezed through a
parser that was designed for something else.

Mappings (see `docs/transit_data.json` and `plan.md` section B):

- operators           -> ImportAgency (ref namespace unused for agencies;
                           `ImportRoute.agency` carries the operator NAME)
- stops               -> ImportStop  (ref = stop.key; latitude/longitude kept
                           as None when the dataset leaves them null - the
                           plan forbids fabricating coordinates)
- routes              -> ImportRoute (ref = route.key; `agency` resolved from
                           `route.agency_id` to the operator's NAME, since
                           the importer matches agencies by name)
- route_stops (top    -> ImportRouteStop (refs via route.key/stop.key). The
  level array)           top-level array only covers red_line; the 4 FR
                         routes carry their stop sequences inside
                         `trips[].stop_times`, so those are ALSO derived
                         here into RouteStop rows (sequence = index+1,
                         distance left null) so the FR routes participate
                         in the routing graph like any other route.
- trips               -> ImportTripPattern + ImportStopTime, keyed by
                         (route_ref, direction). Direction normalized
                         Forward/Backward -> forward/backward. A null
                         `departure_offset_s` (present on FR-14's terminal
                         stop) is treated as "no dwell": departure =
                         arrival.
- service_calendars   -> not mapped (they describe service-day membership,
                         which the importer handles via the `service_date`
                         argument, not the dataset); transfers are out of
                         scope for this phase.

Everything here is pure (dict in, `ImportDataset` out) - no database
session, no I/O except the optional file loader.
"""

from __future__ import annotations

import json
from pathlib import Path

from seeding.import_schema import (
    ImportAgency,
    ImportDataset,
    ImportRoute,
    ImportRouteStop,
    ImportStop,
    ImportStopTime,
    ImportTripPattern,
)

# `transit_data.json` describes stops in both the `stops` array and inside
# `trips[].stop_times`; these are the only two places stop refs appear and
# both are covered below, so no cross-check is needed beyond the resolution
# helpers. Direction values come straight from the research data, which uses
# the capitalized forms.
_DIRECTION_NORMALIZATION = {"Forward": "forward", "Backward": "backward"}


def transit_data_to_dataset(document: dict) -> ImportDataset:
    """Convert a decoded `transit_data.json` document into an
    `ImportDataset`. Raises `KeyError` if a reference (agency_id on a
    route, stop_id on a route_stop or stop_time) doesn't resolve - the
    research dataset is internally consistent today, and an unresolvable
    ref is a dataset bug worth surfacing loudly rather than silently
    skipping."""

    operators_by_id = {op["id"]: op for op in document["operators"]}
    stops_by_id = {stop["id"]: stop for stop in document["stops"]}
    routes_by_id = {route["id"]: route for route in document["routes"]}

    agencies = tuple(
        ImportAgency(
            name=op["name"],
            network_type=op.get("network_type"),
        )
        for op in document["operators"]
    )

    stops = tuple(
        ImportStop(
            ref=stop["key"],
            name=stop["name"],
            latitude=stop.get("latitude"),
            longitude=stop.get("longitude"),
        )
        for stop in document["stops"]
    )

    routes = tuple(
        ImportRoute(
            ref=route["key"],
            agency=operators_by_id[route["agency_id"]]["name"],
            short_name=route["short_name"],
            long_name=route.get("long_name"),
            color=route.get("color"),
        )
        for route in document["routes"]
    )

    # Top-level route_stops (only red_line today). FR-route stop sequences
    # live inside trips[].stop_times - derived below.
    route_stops = [
        ImportRouteStop(
            route_ref=routes_by_id[rs["route_id"]]["key"],
            stop_ref=stops_by_id[rs["stop_id"]]["key"],
            sequence=rs["sequence"],
            distance_along_route_m=rs.get("distance_along_route_m"),
        )
        for rs in document["route_stops"]
    ]

    routes_with_top_level_stops = {rs["route_id"] for rs in document["route_stops"]}

    trip_patterns: list[ImportTripPattern] = []
    trip_stop_times: dict[tuple[str, str], tuple[ImportStopTime, ...]] = {}

    for trip in document["trips"]:
        route = routes_by_id[trip["route_id"]]
        direction = _DIRECTION_NORMALIZATION[trip["direction"]]
        route_ref = route["key"]

        pattern = ImportTripPattern(
            route_ref=route_ref,
            direction=direction,
            headway_minutes=trip["headway_min"],
            total_trips_per_day=trip["total_trips_per_day"],
            first_trip_start=trip["first_trip_start"],
            last_trip_start=trip.get("last_trip_start"),
            source_pdf=trip.get("source"),
            confidence=trip.get("confidence", "UNKNOWN"),
        )
        trip_patterns.append(pattern)

        stop_times: list[ImportStopTime] = []
        for i, st in enumerate(trip["stop_times"]):
            stop = stops_by_id[st["stop_id"]]
            arrival = st["arrival_offset_s"]
            departure = st.get("departure_offset_s")
            if departure is None:
                # No dwell time modeled (FR-14's terminal stop): treat
                # arrival == departure.
                departure = arrival
            stop_times.append(
                ImportStopTime(
                    stop_ref=stop["key"],
                    sequence=i + 1,
                    arrival_offset_s=arrival,
                    departure_offset_s=departure,
                )
            )
        trip_stop_times[(route_ref, direction)] = tuple(stop_times)

        # Derive RouteStop rows for routes whose only ordered stop sequence
        # lives in this trip's stop_times (the FR routes). Skip routes that
        # already have top-level route_stops (red_line) to avoid a second,
        # conflicting source of truth.
        if trip["route_id"] not in routes_with_top_level_stops:
            for i, st in enumerate(trip["stop_times"]):
                route_stops.append(
                    ImportRouteStop(
                        route_ref=route_ref,
                        stop_ref=stops_by_id[st["stop_id"]]["key"],
                        sequence=i + 1,
                        distance_along_route_m=None,
                    )
                )

    return ImportDataset(
        agencies=agencies,
        stops=stops,
        routes=routes,
        route_stops=tuple(route_stops),
        trip_patterns=tuple(trip_patterns),
        trip_stop_times=trip_stop_times,
    )


def load_transit_data(path: str | Path) -> ImportDataset:
    """Load `docs/transit_data.json` from disk and convert it."""
    with open(path, encoding="utf-8") as fh:
        document = json.load(fh)
    return transit_data_to_dataset(document)