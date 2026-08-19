"""
Journey-search API: `POST /transit/journeys/search`.

This is the API-layer glue between the routing engine (Steps 1-7,
unchanged and not re-implemented here) and HTTP: it obtains the cached
`TransitGraph` via `api.graph_state.get_transit_graph` (never rebuilds
it), snaps the request's raw origin/destination coordinates to candidate
stops via the existing `routing.snapping.snap_origin`/`snap_destination`,
runs the existing pure `routing.search.find_shortest_path`, reconstructs
the result via the existing `routing.journey.build_journey`, and maps
that internal `Journey` into the Pydantic schemas from
`api/transit/journey_schemas.py` - never returning a raw dataclass,
SQLAlchemy model, or GeoAlchemy object.

One deliberate, minimal exception to "the cached graph is the routing
data source": after the search completes, this module runs a single
batch query for the `Route`/`Agency` rows behind whichever routes ended
up in the winning journey - full route/agency metadata (short_name,
color, agency name, ...) was never part of the graph's minimal
`RideEdge`/`GraphNode` structures (nor should it be), so it isn't
available from `graph` alone. This is response-*building* after the
search, not part of the search itself - the search (`find_shortest_path`)
still only ever reads `graph`. That same batch query also pulls each
route's road-following geometry (Phase 6, plan.md section H item 6),
reusing `api.transit.router`'s `_route_geometry_json_expr`/
`_route_geometry_read` - the exact same `ST_AsGeoJSON` extraction and
null-handling `GET /transit/routes/{id}` already uses - rather than a
second, possibly-drifting implementation of "how do we turn `Route.path`
into JSON" for this one caller.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.graph_state import get_transit_graph
from api.transit.journey_schemas import (
    JourneyLegRead,
    JourneyRead,
    JourneySearchRequest,
    JourneySearchResponse,
    RideLegRead,
    WalkLegRead,
)
from api.transit.router import _route_geometry_json_expr, _route_geometry_read
from api.transit.schemas import AgencyRead, Coordinates, RouteListItem, StopRead
from db.models import Route
from db.session import get_session
from routing.config import TRANSFER_PENALTY_S
from routing.geo import Point
from routing.graph import GraphNode, TransitGraph
from routing.journey import Journey, RideLeg, WalkLeg, build_journey
from routing.search import (
    fastest_edge_cost,
    fewest_transfers_edge_cost,
    find_shortest_path,
    least_walking_edge_cost,
)
from routing.snapping import DEFAULT_MAX_WALK_M, snap_destination, snap_origin

router = APIRouter(prefix="/transit/journeys", tags=["transit", "journeys"])

# One entry per RoutingObjective (api/transit/journey_schemas.py) - adding
# a fourth objective later means adding one entry here, not branching
# logic anywhere else in this module or in routing.search's search loop.
_EDGE_COST_FN_BY_OBJECTIVE = {
    "fastest": fastest_edge_cost,
    "fewest_transfers": fewest_transfers_edge_cost,
    "least_walking": least_walking_edge_cost,
}


def _stop_read_from_graph(graph: TransitGraph, stop_id: uuid.UUID) -> StopRead:
    """Build a `StopRead` for `stop_id` directly from the already-loaded
    `GraphNode` - no additional database query, since `graph` already
    carries every stop's name and coordinates (see `routing.graph`)."""
    node: GraphNode = graph.nodes[stop_id]
    return StopRead(
        id=node.stop_id,
        name=node.name,
        location=Coordinates(latitude=node.latitude, longitude=node.longitude),
        distance_m=None,
    )


async def _fetch_routes_by_id(
    session: AsyncSession, route_ids: set[uuid.UUID]
) -> dict[uuid.UUID, tuple[Route, str | None]]:
    """Batch-fetch every `Route` (with its `Agency` eagerly loaded) AND
    its road-following geometry GeoJSON (Phase 6) behind `route_ids` in a
    single query - not one query per `RideLeg`, avoiding an N+1 even when
    a journey has several transfers. Returns `{route_id: (route,
    geometry_json)}`; `geometry_json` is `None` exactly when that
    route's `path` hasn't been generated yet, same as
    `GET /transit/routes/{id}`.
    """
    if not route_ids:
        return {}
    result = await session.execute(
        select(Route, _route_geometry_json_expr())
        .where(Route.id.in_(route_ids))
        .options(selectinload(Route.agency))
    )
    return {route.id: (route, geometry_json) for route, geometry_json in result.all()}


def _walk_leg_to_schema(
    leg: WalkLeg,
    graph: TransitGraph,
    origin_location: Coordinates,
    destination_location: Coordinates,
) -> WalkLegRead:
    from_stop = (
        _stop_read_from_graph(graph, leg.from_stop_id)
        if leg.from_stop_id is not None
        else None
    )
    to_stop = (
        _stop_read_from_graph(graph, leg.to_stop_id)
        if leg.to_stop_id is not None
        else None
    )
    return WalkLegRead(
        from_stop=from_stop,
        to_stop=to_stop,
        from_location=from_stop.location if from_stop is not None else origin_location,
        to_location=to_stop.location if to_stop is not None else destination_location,
        distance_m=leg.distance_m,
        duration_s=leg.duration_s,
    )


def _ride_leg_to_schema(
    leg: RideLeg, graph: TransitGraph, routes_by_id: dict[uuid.UUID, tuple[Route, str | None]]
) -> RideLegRead:
    route, geometry_json = routes_by_id[leg.route_id]
    return RideLegRead(
        route=RouteListItem.model_validate(route),
        agency=AgencyRead.model_validate(route.agency),
        board_stop=_stop_read_from_graph(graph, leg.board_stop_id),
        alight_stop=_stop_read_from_graph(graph, leg.alight_stop_id),
        intermediate_stops=[
            _stop_read_from_graph(graph, stop_id) for stop_id in leg.intermediate_stop_ids
        ],
        duration_s=leg.duration_s,
        route_geometry=_route_geometry_read(route, geometry_json),
    )


async def _journey_to_schema(
    journey: Journey,
    graph: TransitGraph,
    session: AsyncSession,
    objective: str,
    origin_location: Coordinates,
    destination_location: Coordinates,
) -> JourneyRead:
    route_ids = {leg.route_id for leg in journey.legs if isinstance(leg, RideLeg)}
    routes_by_id = await _fetch_routes_by_id(session, route_ids)

    legs: list[JourneyLegRead] = []
    for leg in journey.legs:
        if isinstance(leg, WalkLeg):
            legs.append(
                _walk_leg_to_schema(leg, graph, origin_location, destination_location)
            )
        else:
            legs.append(_ride_leg_to_schema(leg, graph, routes_by_id))

    # Passenger-facing total INCLUDES transfer penalty time - see
    # JourneyRead's docstring for why this differs from
    # Journey.total_duration_s, and why the adjustment happens here rather
    # than inside routing.journey.
    passenger_facing_total_duration_s = journey.total_duration_s + (
        journey.transfer_count * TRANSFER_PENALTY_S
    )

    return JourneyRead(
        objective=objective,
        total_duration_s=passenger_facing_total_duration_s,
        total_walk_m=journey.total_walk_m,
        transfer_count=journey.transfer_count,
        legs=legs,
    )


@router.post("/search", response_model=JourneySearchResponse)
async def search_journeys(
    search_request: JourneySearchRequest,
    session: AsyncSession = Depends(get_session),
    graph: TransitGraph = Depends(get_transit_graph),
) -> JourneySearchResponse:
    """Find a journey from `origin` to `destination`.

    Three distinct outcomes, per this step's requirements:

    1. No stop is within walking range of `origin`, or none is within
       range of `destination` -> `422`, with a detail identifying which
       end failed. Chosen over `404` since the coordinates themselves are
       valid - there's simply no usable candidate to search from/to,
       which reads more like "this request can't be processed" than "a
       specific resource wasn't found".
    2. Candidate stops exist near both ends, but no transit path connects
       any origin candidate to any destination candidate (a disconnected
       part of the network) -> a completely normal, successful `200`
       with `journeys: []`. This is a legitimate answer to a well-formed
       question, not a client error.
    3. A path is found -> `200` with exactly one journey in `journeys`
       (this MVP's Dijkstra produces a single optimal path; the list
       shape stays open for future alternatives).
    """
    max_walk_m = search_request.max_walk_m or DEFAULT_MAX_WALK_M

    origin_point = Point(
        latitude=search_request.origin.latitude,
        longitude=search_request.origin.longitude,
    )
    destination_point = Point(
        latitude=search_request.destination.latitude,
        longitude=search_request.destination.longitude,
    )

    origin_connections = await snap_origin(session, origin_point, max_walk_m)
    if not origin_connections:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No stops found within walking distance of the origin.",
        )

    destination_connections = await snap_destination(
        session, destination_point, max_walk_m
    )
    if not destination_connections:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No stops found within walking distance of the destination.",
        )

    edge_cost_fn = _EDGE_COST_FN_BY_OBJECTIVE[search_request.objective]
    search_result = find_shortest_path(
        graph, origin_connections, destination_connections, edge_cost_fn=edge_cost_fn
    )

    if search_result is None:
        return JourneySearchResponse(journeys=[])

    journey = build_journey(search_result)
    journey_read = await _journey_to_schema(
        journey,
        graph,
        session,
        search_request.objective,
        search_request.origin,
        search_request.destination,
    )

    return JourneySearchResponse(journeys=[journey_read])
