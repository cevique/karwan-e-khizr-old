"""
FastAPI application entrypoint for the Karwan-e-Khizr backend.

Run locally (from the `backend/` directory):

    uvicorn main:app --reload

This module wires up the FastAPI application instance, the API router
aggregator, CORS, and the routing graph's startup lifecycle (see
`api.graph_state`).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

# CORS (Phase 6, plan.md section M/H: "frontend developer can integrate
# against stable, documented API contracts" - a browser-based map client
# cannot call this API cross-origin at all without this).
#
# `allow_origins=["*"]` deliberately: every endpoint a browser map client
# actually needs (the static transit network, journey search, realtime
# vehicle positions/ETAs) is already publicly readable with no
# authentication (see api/router.py - only `/admin/*` requires
# `require_role(ROLE_ADMIN)`, and admin tooling is not a browser-map
# frontend's concern). `allow_credentials=False` is paired with the
# wildcard origin deliberately, not by oversight - the admin/auth flows
# use an `Authorization: Bearer <token>` header (see api/auth/router.py),
# not cookies, so no request in this API relies on
# `credentials: include`/cookie-based CORS at all; Starlette's
# `CORSMiddleware` also refuses `allow_credentials=True` combined with a
# wildcard origin outright, so this pairing is the only valid one that
# still lets any origin's Authorization header through
# (`allow_headers=["*"]` covers that). Tightening `allow_origins` to a
# specific known frontend domain is a deployment-time config change, not
# a code change - nothing here hardcodes an environment-specific origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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
