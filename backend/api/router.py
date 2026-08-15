"""
Top-level API router aggregator.

Individual feature modules (e.g., transit, tickets, users) each define
their own `APIRouter` and get included here as they're implemented -
keeping `main.py` decoupled from the growing set of feature routers.
"""

from fastapi import APIRouter, Depends

from api.admin.router import router as admin_router
from api.auth.router import router as auth_router
from api.dev.router import router as dev_router
from api.fares.router import router as fares_router
from api.tickets.router import router as tickets_router
from api.transit.journeys import router as journeys_router
from api.transit.realtime.control_router import (
    router as realtime_simulation_control_router,
)
from api.transit.realtime.router import router as realtime_router
from api.transit.router import router as transit_router
from api.transit.vehicles.router import router as vehicles_router
from api.users.router import router as users_router
from db.models.user import ROLE_ADMIN
from users.dependencies import require_role

api_router = APIRouter()

api_router.include_router(transit_router)
api_router.include_router(journeys_router)

# Realtime + simulation (Claude A workstream). `vehicles_router` (roster:
# "what vehicles/trips exist") and `realtime_router` (public, read-only
# "where is this vehicle right now") are always safe to mount.
api_router.include_router(vehicles_router)
api_router.include_router(realtime_router)

# Dev/demo simulation control (start/stop a trip, force a position
# snapshot, etc.) - intentionally unauthenticated, as designed: see
# `api/transit/realtime/control_router.py`'s module docstring. This is a
# deliberate architecture decision (a hackathon dev/demo control surface),
# not an oversight - do not put this behind production traffic without
# adding auth first.
api_router.include_router(realtime_simulation_control_router)

# Auth + users + fares + ticketing (Claude B workstream).
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(fares_router)
api_router.include_router(tickets_router)

# Data/seeding/import/admin/dev tooling (Claude C workstream).
#
# `admin_router` exposes destructive, production-style operations (seed
# reset, replace-mode seed/import, forced graph rebuild) - see
# `api/admin/router.py`'s module docstring, which explicitly says not to
# mount it publicly without auth. It is gated here with
# `require_role(ROLE_ADMIN)` via `include_router(..., dependencies=[...])`
# - this only adds the dependency to the copy of the routes mounted on
# THIS app; `api.admin.router.router`'s own route objects are untouched,
# so C's existing tests (which mount `admin_router` directly on their own
# bare test app, with no auth) continue to work unmodified.
api_router.include_router(
    admin_router, dependencies=[Depends(require_role(ROLE_ADMIN))]
)

# `dev_router` is read-only (status/validate-only, never mutates the
# database - see `api/dev/router.py`'s module docstring) and is left
# unauthenticated, matching that documented design intent. Treat this as
# a development/staging-only surface regardless.
api_router.include_router(dev_router)
