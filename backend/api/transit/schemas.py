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
    """Public representation of a Stop, including its coordinates.

    `distance_m` is only populated when this Stop came from the
    nearby-stops query (`GET /transit/stops?latitude=...`); it's `None` for
    a plain listing or a direct `GET /transit/stops/{stop_id}` lookup,
    where "distance from where?" has no defined answer.
    """

    id: uuid.UUID
    name: str
    location: Coordinates
    distance_m: float | None = None


class RouteStopRead(BaseModel):
    """A single ordered stop within a Route's detail response."""

    sequence: int
    distance_along_route_m: decimal.Decimal | None
    stop: StopRead


class RouteDetail(BaseModel):
    """Full representation of a Route, including its ordered stops."""

    id: uuid.UUID
    agency_id: uuid.UUID
    short_name: str
    long_name: str | None
    color: str | None
    agency: AgencyRead
    stops: list[RouteStopRead]
