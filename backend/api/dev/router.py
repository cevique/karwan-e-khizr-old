"""
Development API router: read-only data-status inspection and dry-run
("validate only, don't persist") checks.

NOT registered on the main application - see `api/admin/router.py`'s
module docstring for why (this router is read-only, but is still kept
out of the public application until a deliberate integration step wires
it in, matching the rest of this workstream's routers). See
`backend/data/README.md` for that manual step.
"""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.dev.schemas import DataStatusResponse, ValidateRequest, ValidationResponse
from db.models import Agency, Route, RouteStop, Stop
from db.session import get_session
from seeding.admin_convert import to_import_dataset
from seeding.seed import get_seed_status, seed_dataset_as_import_dataset
from seeding.validation import validate_dataset

router = APIRouter(prefix="/dev", tags=["dev"])


async def _table_count(session: AsyncSession, model) -> int:
    return (
        await session.execute(sa.select(sa.func.count()).select_from(model))
    ).scalar_one()


@router.get("/status", response_model=DataStatusResponse)
async def status(
    request: Request, session: AsyncSession = Depends(get_session)
) -> DataStatusResponse:
    """Snapshot of the current static transit data: total row counts,
    how much of the deterministic seed dataset is present, and whether a
    routing graph is currently loaded on `app.state` (read-only - never
    triggers a build; see `api/admin/router.py`'s `/admin/graph/rebuild`
    for that)."""
    agencies_total = await _table_count(session, Agency)
    routes_total = await _table_count(session, Route)
    stops_total = await _table_count(session, Stop)
    route_stops_total = await _table_count(session, RouteStop)

    seed_status = await get_seed_status(session)

    graph = getattr(request.app.state, "transit_graph", None)

    return DataStatusResponse(
        agencies_total=agencies_total,
        routes_total=routes_total,
        stops_total=stops_total,
        route_stops_total=route_stops_total,
        seed_agencies_present=seed_status["seed_agencies_present"],
        seed_agencies_total=seed_status["seed_agencies_total"],
        seed_stops_present=seed_status["seed_stops_present"],
        seed_stops_total=seed_status["seed_stops_total"],
        seed_routes_present=seed_status["seed_routes_present"],
        seed_routes_total=seed_status["seed_routes_total"],
        transit_graph_loaded=graph is not None,
        transit_graph_node_count=len(graph.nodes) if graph is not None else None,
        transit_graph_ride_edge_count=(
            len(graph.ride_edges) if graph is not None else None
        ),
        transit_graph_walk_edge_count=(
            len(graph.walk_edges) if graph is not None else None
        ),
    )


@router.post("/validate", response_model=ValidationResponse)
async def validate(payload: ValidateRequest) -> ValidationResponse:
    """Validate a dataset (same shape as `POST /admin/import`'s body)
    without persisting anything - no database session is even used here.
    Useful for previewing what an import would report before actually
    running it."""
    dataset = to_import_dataset(payload)
    result = validate_dataset(dataset)
    return ValidationResponse(
        is_valid=result.is_valid,
        errors=[e.__dict__ for e in result.errors],
        warnings=[w.__dict__ for w in result.warnings],
    )


@router.post("/validate/seed", response_model=ValidationResponse)
async def validate_seed() -> ValidationResponse:
    """Validate the deterministic demo dataset (`data.seed_dataset`)
    itself - a sanity check for whoever edits that file, independent of
    any database."""
    result = validate_dataset(seed_dataset_as_import_dataset())
    return ValidationResponse(
        is_valid=result.is_valid,
        errors=[e.__dict__ for e in result.errors],
        warnings=[w.__dict__ for w in result.warnings],
    )
