"""
API response schemas for the static transit network (Agency / Route / Stop).

Deliberately separate from `db.models` - these are never `model_validate`'d
directly off an ORM instance for anything containing a geography/geometry
column (`Stop.location`, `Route.path`), since GeoAlchemy2 loads those as
WKB elements, not something Pydantic/JSON can serialize on its own. Schemas
that need coordinates are built explicitly in `router.py` from values
already extracted in SQL (see the module docstring there for why).
"""

from __future__ import annotations

import decimal
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Coordinates(BaseModel):
    """A WGS84 (SRID 4326) latitude/longitude pair.

    Chosen over GeoJSON for point locations: a mobile client places a
    `Stop` directly as a marker on a native map SDK (Google Maps / Mapbox /
    MapKit), all of which take a plain lat/lng pair - GeoJSON's `Point`
    would just be unwrapped back into this same shape on the client. GeoJSON
    would earn its complexity for `Route.path` (a LineString, i.e. a real
    "geometry" a client draws as a polyline) - but serializing `Route.path`
    is out of scope for this step (see router.py's module docstring).
    """

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class AgencyRead(BaseModel):
    """Public representation of an Agency."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    network_type: str | None


class RouteListItem(BaseModel):
    """Summary representation of a Route, as returned by the list endpoint.

    Deliberately lean: no embedded Agency object (only its id - the client
    already knows it if it filtered by `agency_id`, and can otherwise fetch
    `GET /transit/agencies` once and join client-side) and no stops, so the
    list endpoint stays a single, unjoined query.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agency_id: uuid.UUID
    short_name: str
    long_name: str | None
    color: str | None


class StopRead(BaseModel):
    """Public representation of a Stop.

    `location` is `None` for stops whose coordinates aren't known yet
    (`Stop.location` is nullable - Phase 1 imports ~105 unlocated stops
    from `docs/transit_data.json`, per `docs/DATA_GAPS.md`). This is a
    deliberate, frontend-visible signal: such a stop can be listed and
    named, but cannot be placed on a map until the geospatial-enrichment
    pass fills it in.

    `distance_m` is only populated when this Stop came from the
    nearby-stops query (`GET /transit/stops?latitude=...`); it's `None` for
    a plain listing or a direct `GET /transit/stops/{stop_id}` lookup,
    where "distance from where?" has no defined answer.
    """

    id: uuid.UUID
    name: str
    location: Coordinates | None
    distance_m: float | None = None


class RouteStopRead(BaseModel):
    """A single ordered stop within a Route's detail response."""

    sequence: int
    distance_along_route_m: decimal.Decimal | None
    stop: StopRead


class RouteGeometryRead(BaseModel):
    """A Route's road-following polyline (Phase 3, plan.md section D/G),
    as GeoJSON - unlike `Coordinates` (a single point), a full LineString
    earns GeoJSON's extra structure since that's what a map client's
    polyline-rendering call typically expects directly (see
    `Coordinates`'s docstring for why single points instead use the
    plainer lat/lng shape).

    Explicitly nullable end-to-end (`type`/`coordinates` both `None`) for
    a Route whose geometry hasn't been generated yet
    (`db/models/route.py`'s `path` is nullable) - the client can then
    render the route's stops as markers only, without a connecting line,
    rather than receiving an error or a fabricated straight-line path.
    `geometry_source`/`geometry_confidence` are always present (even when
    `coordinates` is null) so the client/dev can tell "not attempted yet"
    (both null) apart from "attempted, OSRM couldn't route it"
    (`geometry_confidence == \"UNKNOWN\"`, still no coordinates) - see
    `db/models/route.py`'s field docstrings.
    """

    type: Literal["LineString"] | None
    coordinates: list[tuple[float, float]] | None = Field(
        None, description="[longitude, latitude] pairs, GeoJSON order."
    )
    geometry_source: str | None
    geometry_confidence: str | None


class RouteDetail(BaseModel):
    """Full representation of a Route, including its ordered stops and
    road-following geometry (Phase 3 adds `geometry`; see
    `RouteGeometryRead`'s docstring for why it's nullable)."""

    id: uuid.UUID
    agency_id: uuid.UUID
    short_name: str
    long_name: str | None
    color: str | None
    agency: AgencyRead
    stops: list[RouteStopRead]
    geometry: RouteGeometryRead
