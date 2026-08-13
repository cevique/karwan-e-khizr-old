"""
FastAPI application entrypoint for the Karwan-e-Khizr backend.

Run locally (from the `backend/` directory):

    uvicorn main:app --reload

This module wires up the FastAPI application instance, the API router
aggregator, and the routing graph's startup lifecycle (see
`api.graph_state`). Authentication and all feature functionality beyond
the static transit API and journey-search plumbing are deliberately out
of scope for this step and will be added in later ones.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.graph_state import build_and_store_graph
from api.health import router as health_router
from api.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the routing graph once at startup and store it on
    `app.state` (see `api.graph_state.build_and_store_graph`), before the
    app begins accepting requests. Deliberately does not catch any
    exception `build_and_store_graph` raises - a database or static-data
    problem must fail startup, not silently start the API with a missing
    or broken routing graph.
    """
    await build_and_store_graph(app)
    yield


app = FastAPI(
    title="Karwan-e-Khizr API",
    description="Public-transit journey planning API for the Karwan-e-Khizr project.",
    version="0.1.0",
    lifespan=lifespan,
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
