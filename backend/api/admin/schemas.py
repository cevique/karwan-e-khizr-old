"""Request/response schemas for the admin API (`api/admin/router.py`)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from seeding.validation import Severity


class SeedRequest(BaseModel):
    mode: Literal["insert", "replace"] = "insert"


class SeedResponse(BaseModel):
    mode: str
    agencies_created: int
    agencies_skipped: int
    stops_created: int
    stops_skipped: int
    routes_created: int
    routes_skipped: int
    route_stops_created: int
    route_stops_skipped: int


class SeedResetResponse(BaseModel):
    detail: str = "Seed dataset rows removed (by deterministic ID only)."


class ValidationIssueSchema(BaseModel):
    severity: Severity
    code: str
    message: str
    location: str


class ImportAgencyIn(BaseModel):
    name: str
    network_type: str | None = None


class ImportStopIn(BaseModel):
    ref: str
    name: str
    latitude: float
    longitude: float


class ImportRouteIn(BaseModel):
    ref: str
    agency: str
    short_name: str
    long_name: str | None = None
    color: str | None = None


class ImportRouteStopIn(BaseModel):
    route_ref: str
    stop_ref: str
    sequence: int
    distance_along_route_m: float | None = None


class ImportRequest(BaseModel):
    """Mirrors `seeding.import_schema.ImportDataset` field-for-field -
    see that module's docstring for the full shape/semantics."""

    agencies: list[ImportAgencyIn] = Field(default_factory=list)
    stops: list[ImportStopIn] = Field(default_factory=list)
    routes: list[ImportRouteIn] = Field(default_factory=list)
    route_stops: list[ImportRouteStopIn] = Field(default_factory=list)


class ImportResponse(BaseModel):
    agencies_created: int
    agencies_updated: int
    stops_created: int
    stops_updated: int
    routes_created: int
    routes_updated: int
    route_stops_created: int
    route_stops_updated: int
    warnings: list[ValidationIssueSchema]


class ImportRejectedResponse(BaseModel):
    """Returned (with HTTP 422) when `ImportValidationError` is raised -
    the dataset was rejected in full; nothing was written."""

    detail: str = "Import dataset failed validation; nothing was written."
    errors: list[ValidationIssueSchema]
    warnings: list[ValidationIssueSchema]


class GraphRebuildResponse(BaseModel):
    node_count: int
    ride_edge_count: int
    walk_edge_count: int


class TripGenerationRequest(BaseModel):
    """`POST /admin/trips/generate`'s request body (plan.md section M,
    Phase 5). `route_id` is an EXISTING `Route` row's id (not a
    `docs/transit_data.json` ref - the admin picks a route already in
    the database, same as every other admin endpoint here)."""

    route_id: uuid.UUID
    service_date: date


class TripGenerationResponse(BaseModel):
    """Scoped-down `ImportReport` fields - only the ones relevant to
    "how many trips/stop_times did this call produce for this one
    route" (see `seeding.trip_generator.dataset_for_route`'s docstring
    for why the response is scoped to one route rather than reusing
    `ImportResponse` wholesale)."""

    route_id: uuid.UUID
    route_short_name: str
    service_date: date
    trips_created: int
    trips_replaced: int
    stop_times_created: int


class TripGenerationRejectedResponse(BaseModel):
    """Returned (with HTTP 404) when the route doesn't exist, or exists
    but has no canonical trip pattern to generate from - see
    `seeding.trip_generator.NoCanonicalTripPattern`."""

    detail: str
