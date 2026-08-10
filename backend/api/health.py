"""
Health and database-readiness endpoint.

Exposes `GET /health` for this step. Liveness and database readiness are
implemented as separate, independently callable functions
(`check_liveness` / `check_database`) so that `/health/live` and
`/health/ready` can be added later as thin wrappers around them, without
reworking this logic.

No new database engine or session factory is created here - the database
check reuses the existing `db.session.get_session` dependency, which is
itself bound to the single application engine configured from
`core.config.settings.DATABASE_URL`.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class ComponentStatus(BaseModel):
    """Status of a single health component (e.g., API process, database)."""

    status: Literal["ok", "error"]


class HealthResponse(BaseModel):
    """Structured response body for GET /health."""

    status: Literal["ok", "error"]
    api: ComponentStatus
    database: ComponentStatus


def check_liveness() -> ComponentStatus:
    """
    Report whether the API process itself is alive.

    Trivial by design: if this function is executing at all, the FastAPI
    process is up and handling requests. Kept as its own function so a
    future `/health/live` endpoint can call it directly without change.
    """
    return ComponentStatus(status="ok")


async def check_database(session: AsyncSession) -> ComponentStatus:
    """
    Report whether the database is reachable by executing `SELECT 1`.

    Uses the caller-provided session (from `db.session.get_session`) rather
    than creating a new engine or session factory. Any failure is logged
    server-side with full detail and reported to the caller only as a
    generic "error" status - no connection string, credentials, or
    exception detail is ever included in the returned value. Kept as its
    own function so a future `/health/ready` endpoint can call it directly
    without change.
    """
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database readiness check failed")
        return ComponentStatus(status="error")
    return ComponentStatus(status="ok")


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> HealthResponse:
    """
    Combined liveness + database readiness check.

    Returns HTTP 200 with overall status "ok" when the API process is alive
    and the database is reachable. Returns HTTP 503 with overall status
    "error" if the database check fails - the application process itself
    keeps running in either case; a failed check here never raises out of
    this handler.
    """
    api_status = check_liveness()
    database_status = await check_database(session)

    overall_ok = api_status.status == "ok" and database_status.status == "ok"
    response.status_code = (
        status.HTTP_200_OK if overall_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return HealthResponse(
        status="ok" if overall_ok else "error",
        api=api_status,
        database=database_status,
    )
