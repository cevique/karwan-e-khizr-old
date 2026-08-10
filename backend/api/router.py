"""
Top-level API router aggregator.

Individual feature modules (e.g., transit, tickets, users) will each define
their own `APIRouter` and get included here as they're implemented in later
steps - keeping `main.py` decoupled from the growing set of feature routers.

No sub-routers are included yet: no feature modules exist at this stage.
"""

from fastapi import APIRouter

api_router = APIRouter()
