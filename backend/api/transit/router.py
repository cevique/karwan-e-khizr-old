"""
Static transit-network API: read-only endpoints for Agency, Route, and
Stop, plus a Route's ordered Stops.

Coordinate extraction: `Stop.location` is a PostGIS `geography(Point)`
column (see db/models/stop.py's docstring for why geography rather than
geometry). GeoAlchemy2 loads that column as an opaque WKB element, not
something Pydantic can serialize - so rather than loading the ORM column
and converting it in Python (which would pull in an extra dependency,
`shapely`, that nothing else in this project needs), latitude/longitude
are extracted directly in SQL via `ST_X`/`ST_Y` (after a `::geometry`
cast, since those functions operate on `geometry`, not `geography`) as
extra selected columns alongside the ORM entity in the same query. This
keeps every list/detail endpoint here to one query (plus, for route
detail, exactly one more to batch-fetch its stops' coordinates) with no
N+1, and avoids a new dependency.

Route geometry (`Route.path`, a LineString) is intentionally NOT
serialized in this step - the task only calls for exposing a Route's
ordered Stops, and a full polyline representation (better done as GeoJSON,
unlike the simple lat/lng pairs used for Stop points) is left for whenever
the mobile client actually needs to render route paths on the map, to
avoid over-engineering this step.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from geoalchemy2 import Geography, Geometry
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.transit.schemas import (
    AgencyRead,
    Coordinates,
    RouteDetail,
    RouteListItem,
    RouteStopRead,
    StopRead,
)
from db.models import Agency, Route, RouteStop, Stop
from db.session import get_session

router = APIRouter(prefix="/transit", tags=["transit"])

# Simple, fixed pagination bounds (see api/transit/schemas.py for why this
# stays deliberately non-elaborate): a client passes `limit`/`offset`; the
# response is a plain JSON array with no total-count/next-page envelope -
# add one if/when the mobile client actually needs it.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# Nearby-stop search radius cap. 20 km comfortably covers "which stops
# could plausibly matter to this map view", while still bounding how much
# of the stops table a single request can force PostGIS to scan.
MAX_RADIUS_M = 20_000


def _longitude_expr():
    return func.ST_X(cast(Stop.location, Geometry)).label("longitude")


def _latitude_expr():
    return func.ST_Y(cast(Stop.location, Geometry)).label("latitude")


def _stop_read(
    stop: Stop,
    longitude: float | None,
    latitude: float | None,
    distance_m: float | None = None,
) -> StopRead:
    location = None
    if longitude is not None and latitude is not None:
        location = Coordinates(latitude=latitude, longitude=longitude)
    return StopRead(
        id=stop.id,
        name=stop.name,
        location=location,
        distance_m=distance_m,
    )


# --------------------------------------------------------------------------
# Agencies
# --------------------------------------------------------------------------


@router.get("/agencies", response_model=list[AgencyRead])
async def list_agencies(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[AgencyRead]:
    """List transit agencies."""
    result = await session.execute(
        select(Agency).order_by(Agency.name).limit(limit).offset(offset)
    )
    return [AgencyRead.model_validate(a) for a in result.scalars().all()]


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.get("/routes", response_model=list[RouteListItem])
async def list_routes(
    agency_id: uuid.UUID | None = Query(
        None, description="Filter to routes belonging to this agency."
    ),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[RouteListItem]:
    """List routes, optionally filtered by agency."""
    stmt = select(Route).order_by(Route.short_name).limit(limit).offset(offset)
    if agency_id is not None:
        stmt = stmt.where(Route.agency_id == agency_id)

    result = await session.execute(stmt)
    return [RouteListItem.model_validate(r) for r in result.scalars().all()]


@router.get("/routes/{route_id}", response_model=RouteDetail)
async def get_route(
    route_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> RouteDetail:
    """Fetch a single Route, including its agency and ordered stops."""
    result = await session.execute(
        select(Route)
        .where(Route.id == route_id)
        .options(
            selectinload(Route.agency),
            selectinload(Route.route_stops).selectinload(RouteStop.stop),
        )
    )
    route = result.scalar_one_or_none()
    if route is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Route not found"
        )

    # `route.route_stops` is already ordered by `sequence` (see the
    # relationship's `order_by` in db/models/route.py), so no re-sorting is
    # needed here. One extra query batch-fetches every involved stop's
    # latitude/longitude in a single round-trip (not one query per stop),
    # since those aren't available directly off the ORM `Stop` instances
    # (see this module's docstring).
    stop_ids = [rs.stop_id for rs in route.route_stops]
    coordinates_by_stop_id: dict[uuid.UUID, tuple[float, float]] = {}
    if stop_ids:
        coord_result = await session.execute(
            select(Stop.id, _longitude_expr(), _latitude_expr()).where(
                Stop.id.in_(stop_ids)
            )
        )
        coordinates_by_stop_id = {
            stop_id: (longitude, latitude)
            for stop_id, longitude, latitude in coord_result.all()
        }

    stops: list[RouteStopRead] = []
    for route_stop in route.route_stops:
        longitude, latitude = coordinates_by_stop_id[route_stop.stop_id]
        stops.append(
            RouteStopRead(
                sequence=route_stop.sequence,
                distance_along_route_m=route_stop.distance_along_route_m,
                stop=_stop_read(route_stop.stop, longitude, latitude),
            )
        )

    return RouteDetail(
        id=route.id,
        agency_id=route.agency_id,
        short_name=route.short_name,
        long_name=route.long_name,
        color=route.color,
        agency=AgencyRead.model_validate(route.agency),
        stops=stops,
    )


# --------------------------------------------------------------------------
# Stops
# --------------------------------------------------------------------------


@router.get("/stops", response_model=list[StopRead])
async def list_stops(
    latitude: float | None = Query(
        None, ge=-90, le=90, description="Center latitude for a nearby-stops search."
    ),
    longitude: float | None = Query(
        None,
        ge=-180,
        le=180,
        description="Center longitude for a nearby-stops search.",
    ),
    radius_m: float | None = Query(
        None,
        gt=0,
        le=MAX_RADIUS_M,
        description="Search radius in meters. Requires latitude and longitude.",
    ),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[StopRead]:
    """
    List stops.

    With no query parameters, returns a plain paginated list. With
    `latitude`, `longitude`, and `radius_m` all provided, instead returns
    stops within `radius_m` meters of that point, nearest first, each with
    `distance_m` populated - a PostGIS `ST_DWithin`/`ST_Distance` query
    against `Stop.location`'s `geography` type, which returns correct
    great-circle meters directly (see db/models/stop.py's docstring).
    """
    geo_params = (latitude, longitude, radius_m)
    some_given = any(p is not None for p in geo_params)
    all_given = all(p is not None for p in geo_params)
    if some_given and not all_given:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "latitude, longitude, and radius_m must all be provided "
                "together for a nearby-stops query."
            ),
        )

    if all_given:
        point = cast(
            func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326),
            Geography,
        )
        distance_expr = func.ST_Distance(Stop.location, point).label("distance_m")
        stmt = (
            select(Stop, _longitude_expr(), _latitude_expr(), distance_expr)
            .where(func.ST_DWithin(Stop.location, point, radius_m))
            .order_by(distance_expr)
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        return [
            _stop_read(stop, lon, lat, distance_m)
            for stop, lon, lat, distance_m in result.all()
        ]

    stmt = (
        select(Stop, _longitude_expr(), _latitude_expr())
        .order_by(Stop.name)
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return [_stop_read(stop, lon, lat) for stop, lon, lat in result.all()]


@router.get("/stops/{stop_id}", response_model=StopRead)
async def get_stop(
    stop_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> StopRead:
    """Fetch a single Stop."""
    result = await session.execute(
        select(Stop, _longitude_expr(), _latitude_expr()).where(Stop.id == stop_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Stop not found"
        )

    stop, longitude, latitude = row
    return _stop_read(stop, longitude, latitude)
