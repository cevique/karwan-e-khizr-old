"""Request/response schemas for the admin API (`api/admin/router.py`)."""

from __future__ import annotations

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
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


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
