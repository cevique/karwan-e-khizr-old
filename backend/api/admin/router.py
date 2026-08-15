"""
Development/admin API router: seed demo data, reset seed data, import
external data, and trigger a routing-graph rebuild.

NOT registered on the main application. `api/router.py` (the top-level
aggregator every other feature router is included into) is explicitly
off-limits for this workstream to modify - see this repository's task
brief - and every operation exposed here is either destructive (seed
reset, replace-mode seed) or otherwise inappropriate to expose publicly
without authentication, which this workstream deliberately does not
implement (auth is a different, parallel workstream). This module only
defines the `APIRouter` object; wiring it into the running application is
a deliberate manual integration step - see `backend/data/README.md`
("Manual integration steps").

No authentication/authorization is implemented or assumed here - do not
mount this router on a publicly reachable path without adding some.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.admin.schemas import (
    GraphRebuildResponse,
    ImportRejectedResponse,
    ImportRequest,
    ImportResponse,
    SeedRequest,
    SeedResetResponse,
    SeedResponse,
    ValidationIssueSchema,
)
from api.graph_state import build_and_store_graph
from db.session import get_session
from seeding.admin_convert import to_import_dataset
from seeding.importer import ImportPersistenceError, ImportValidationError, import_dataset
from seeding.parsers import ImportParseError, parse_csv_dataset
from seeding.seed import clear_seed_data, seed_database

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/seed", response_model=SeedResponse)
async def seed(
    body: SeedRequest = SeedRequest(),
    session: AsyncSession = Depends(get_session),
) -> SeedResponse:
    """Apply the deterministic demo dataset (`data.seed_dataset`).

    `mode="insert"` (default) only creates rows that don't already exist
    (safe to call repeatedly). `mode="replace"` is DESTRUCTIVE: it first
    deletes every row the seed dataset owns (see `seeding.seed.
    clear_seed_data`) and then re-inserts it fresh - still scoped to the
    seed dataset's own deterministic IDs only.
    """
    report = await seed_database(session, mode=body.mode)
    return SeedResponse(**report.__dict__)


@router.post("/seed/reset", response_model=SeedResetResponse)
async def seed_reset(session: AsyncSession = Depends(get_session)) -> SeedResetResponse:
    """DESTRUCTIVE: delete every row the seed dataset owns (by
    deterministic ID only - see `seeding.seed.clear_seed_data`). Does not
    touch any data outside the seed dataset's own IDs."""
    await clear_seed_data(session)
    return SeedResetResponse()


async def _persist_dataset(session: AsyncSession, dataset) -> ImportResponse:
    """Shared body of both import endpoints below (JSON and CSV) - the
    only difference between them is how the raw request became a
    `seeding.import_schema.ImportDataset`; persistence and error mapping
    to HTTP responses are identical."""
    try:
        report = await import_dataset(session, dataset)
    except ImportValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ImportRejectedResponse(
                errors=[ValidationIssueSchema(**vars(i)) for i in exc.result.errors],
                warnings=[ValidationIssueSchema(**vars(i)) for i in exc.result.warnings],
            ).model_dump(),
        ) from exc
    except ImportPersistenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return ImportResponse(
        agencies_created=report.agencies_created,
        agencies_updated=report.agencies_updated,
        stops_created=report.stops_created,
        stops_updated=report.stops_updated,
        routes_created=report.routes_created,
        routes_updated=report.routes_updated,
        route_stops_created=report.route_stops_created,
        route_stops_updated=report.route_stops_updated,
        warnings=[ValidationIssueSchema(**vars(w)) for w in report.warnings],
    )


@router.post(
    "/import",
    response_model=ImportResponse,
    responses={422: {"model": ImportRejectedResponse}},
)
async def import_data(
    payload: ImportRequest,
    session: AsyncSession = Depends(get_session),
) -> ImportResponse:
    """Validate then persist an external dataset (JSON body - see
    `ImportRequest`/`seeding.import_schema.ImportDataset` for the shape).
    Rejected in full (HTTP 422, nothing written) if validation finds any
    error-level issue; rolled back in full if persistence itself fails
    partway through.
    """
    dataset = to_import_dataset(payload)
    return await _persist_dataset(session, dataset)


@router.post(
    "/import/csv",
    response_model=ImportResponse,
    responses={422: {"model": ImportRejectedResponse}},
)
async def import_data_csv(
    agencies: UploadFile | None = File(None),
    stops: UploadFile | None = File(None),
    routes: UploadFile | None = File(None),
    route_stops: UploadFile | None = File(None),
    session: AsyncSession = Depends(get_session),
) -> ImportResponse:
    """Same as `POST /admin/import`, but for four CSV files uploaded as
    multipart form fields (`agencies`, `stops`, `routes`, `route_stops`;
    any may be omitted for "no rows of this kind") instead of one JSON
    body. See `seeding.parsers.parse_csv_dataset` for the expected header
    row of each file.
    """

    async def _read(upload: UploadFile | None) -> str:
        if upload is None:
            return ""
        return (await upload.read()).decode("utf-8")

    try:
        dataset = parse_csv_dataset(
            agencies_csv=await _read(agencies),
            stops_csv=await _read(stops),
            routes_csv=await _read(routes),
            route_stops_csv=await _read(route_stops),
        )
    except ImportParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return await _persist_dataset(session, dataset)


@router.post("/graph/rebuild", response_model=GraphRebuildResponse)
async def rebuild_graph(request: Request) -> GraphRebuildResponse:
    """Rebuild the cached `TransitGraph` from the current database
    contents and store it on `app.state`, exactly as startup does.

    Calls the EXISTING `api.graph_state.build_and_store_graph(app)` -
    the same function `main.py`'s lifespan calls at startup - rather
    than building a graph any other way, so there is exactly one code
    path that ever constructs a `TransitGraph`. Use this after seeding
    or importing static data into an already-running application so its
    routing graph picks up the change without a restart.
    """
    graph = await build_and_store_graph(request.app)
    return GraphRebuildResponse(
        node_count=len(graph.nodes),
        ride_edge_count=len(graph.ride_edges),
        walk_edge_count=len(graph.walk_edges),
    )
