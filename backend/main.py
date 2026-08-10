"""
FastAPI application entrypoint for the Karwan-e-Khizr backend.

Run locally (from the `backend/` directory):

    uvicorn main:app --reload

This module only wires up the FastAPI application instance and the API
router aggregator. Database lifecycle management, the health/readiness
endpoint, authentication, and all feature functionality are deliberately
out of scope for this step and will be added in later ones.
"""

from fastapi import FastAPI

from api.health import router as health_router
from api.router import api_router

app = FastAPI(
    title="Karwan-e-Khizr API",
    description="Public-transit journey planning API for the Karwan-e-Khizr project.",
    version="0.1.0",
)

# Health/readiness endpoints are mounted directly on the app, unprefixed, so
# they stay at the conventional infrastructure path `/health` rather than
# under the versioned `/api` prefix used for feature routes below - this
# matches how liveness/readiness probes (e.g., container orchestrators) are
# typically configured to hit a fixed, un-namespaced path.
app.include_router(health_router)

app.include_router(api_router, prefix="/api")


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Minimal root endpoint confirming the application is running.

    This is intentionally not the /health readiness/liveness endpoint
    (no database check is performed here) - it exists only as a simple,
    verifiable signal that the FastAPI application itself started
    correctly.
    """
    return {"name": app.title, "version": app.version, "status": "ok"}
