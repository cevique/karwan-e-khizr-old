"""Request/response schemas for the dev API (`api/dev/router.py`)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from api.admin.schemas import ImportRequest, ValidationIssueSchema


class DataStatusResponse(BaseModel):
    agencies_total: int
    routes_total: int
    stops_total: int
    route_stops_total: int
    seed_agencies_present: int
    seed_agencies_total: int
    seed_stops_present: int
    seed_stops_total: int
    seed_routes_present: int
    seed_routes_total: int
    transit_graph_loaded: bool
    transit_graph_node_count: int | None = None
    transit_graph_ride_edge_count: int | None = None
    transit_graph_walk_edge_count: int | None = None


class ValidateRequest(ImportRequest):
    """Same shape as `ImportRequest` - validated but never persisted."""


class ValidationResponse(BaseModel):
    is_valid: bool
    errors: list[ValidationIssueSchema] = Field(default_factory=list)
    warnings: list[ValidationIssueSchema] = Field(default_factory=list)
