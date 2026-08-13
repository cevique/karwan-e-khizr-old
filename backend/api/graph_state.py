"""
FastAPI-facing wiring for the routing graph's lifecycle: building it at
startup, storing it on `app.state`, and providing a small, explicit way to
rebuild it later plus a clean way for request handlers to obtain it.

This module intentionally lives in `api/`, not `routing/`: `routing` must
stay importable and testable without any FastAPI dependency (see
`routing.graph`/`routing.search`'s own module docstrings on this), and
everything here is FastAPI-specific (`FastAPI`, `Request`, `app.state`).
It reuses the existing `db.session.AsyncSessionLocal` session factory - no
second engine or session factory is created here.
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from db.session import AsyncSessionLocal
from routing.graph import TransitGraph, build_graph

# The app.state attribute name the current TransitGraph is stored under.
# Centralized here (not a string literal repeated in two places) so
# build_and_store_graph and get_transit_graph can never drift apart.
_STATE_ATTRIBUTE = "transit_graph"


async def build_and_store_graph(app: FastAPI) -> TransitGraph:
    """Build a fresh `TransitGraph` from the current database contents and
    store it on `app.state`, replacing whatever graph (if any) was there
    before. This is both the startup path (called once from `main.py`'s
    lifespan) and the manual-rebuild path (safe to call again later, e.g.
    from a future internal endpoint or a one-off script).

    Safe replacement, without any locking: `build_graph` always returns a
    brand new, independent, read-only `TransitGraph` (see
    `routing.graph`'s own docstring - it is "pure with respect to routing
    state" and never mutates or reuses anything from a previous call).
    This function fully finishes building that new graph - using its own,
    freshly opened session - *before* the single `app.state` attribute
    assignment that makes it "live" for new requests. Any request already
    in flight holds its own reference to the previous `TransitGraph`
    object (handed out by `get_transit_graph`, which reads `app.state`
    exactly once per request) and is completely unaffected by a
    concurrent rebuild: that reference stays valid and correct, since the
    object it points to is immutable by construction and this function
    never mutates it - only ever replaces which object `app.state` points
    to next.

    Uses the existing `db.session.AsyncSessionLocal` factory - no second
    engine or session factory is created here.

    Deliberately has no `try`/`except` around `build_graph`: any exception
    (a database connectivity problem, or invalid static data causing
    construction to fail) propagates straight to the caller. When called
    from `main.py`'s lifespan at startup, that means application startup
    fails loudly and the server never starts serving requests with a
    missing or broken graph - silently falling back to an empty graph is
    exactly what this step's requirements rule out.
    """
    async with AsyncSessionLocal() as session:
        graph = await build_graph(session)

    setattr(app.state, _STATE_ATTRIBUTE, graph)
    return graph


def get_transit_graph(request: Request) -> TransitGraph:
    """FastAPI dependency: the `TransitGraph` current as of when this
    request started being handled.

    `Depends(get_transit_graph)` reads `request.app.state` exactly once,
    at dependency-resolution time - so within a single request the graph
    reference is stable and internally consistent even if a rebuild
    happens concurrently elsewhere (see `build_and_store_graph`'s
    docstring for why that's safe).

    Raises `AttributeError` if called before `build_and_store_graph` has
    ever run for this app (e.g. a request handled outside the app's
    lifespan, or a script that imports `main.app` without driving its
    lifespan) - there is deliberately no silent fallback to an empty
    graph here either.
    """
    return getattr(request.app.state, _STATE_ATTRIBUTE)
