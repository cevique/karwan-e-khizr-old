"""
Top-level API router aggregator.

Individual feature modules (e.g., transit, tickets, users) each define
their own `APIRouter` and get included here as they're implemented -
keeping `main.py` decoupled from the growing set of feature routers.
"""

from fastapi import APIRouter

from api.transit.router import router as transit_router

api_router = APIRouter()

api_router.include_router(transit_router)
