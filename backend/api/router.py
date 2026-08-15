"""
Top-level API router aggregator.

Individual feature modules (e.g., transit, tickets, users) each define
their own `APIRouter` and get included here as they're implemented -
keeping `main.py` decoupled from the growing set of feature routers.
"""

from fastapi import APIRouter

from api.transit.journeys import router as journeys_router
from api.transit.realtime.control_router import (
    router as realtime_simulation_control_router,
)
from api.transit.realtime.router import router as realtime_router
from api.transit.router import router as transit_router
from api.transit.vehicles.router import router as vehicles_router

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
# deliberate architecture decision (a hackathon dev/demo control surface,
# analogous to `api/dev/*` added later), not an oversight - do not put
# this behind production traffic without adding auth first.
api_router.include_router(realtime_simulation_control_router)
