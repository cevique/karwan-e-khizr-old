#!/usr/bin/env python3
"""
Verify the routing graph can be built from the database's current static
transit data, and print a summary - without touching any running
application's `app.state` (see below for why, and how this differs from
an actual live rebuild).

Run from the `backend/` directory:

    python scripts/verify_graph_buildable.py

Calls the EXISTING `routing.graph.build_graph` (the same function
`api.graph_state.build_and_store_graph` calls) directly with its own
session - not `build_and_store_graph` itself, since that function's job
is specifically to store the result on a live FastAPI app's `app.state`,
which only makes sense for an app that's actually running. This script
never duplicates graph-construction logic; it's a read-only smoke test
around the one function that already contains it.

To actually rebuild the graph a RUNNING application is serving requests
from, use the admin API's `POST /admin/graph/rebuild` (see
`backend/data/README.md`) - that's the only path that updates a live
`app.state`, once the admin router is wired into that application.
"""

from __future__ import annotations

import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def _run() -> None:
    from db.session import AsyncSessionLocal
    from routing.graph import build_graph

    async with AsyncSessionLocal() as session:
        graph = await build_graph(session)

    print(f"nodes (stops):     {len(graph.nodes)}")
    print(f"ride edges:        {len(graph.ride_edges)}")
    print(f"walk edges:        {len(graph.walk_edges)}")

    if not graph.nodes:
        print(
            "\nNo stops found - the database has no static transit data yet. "
            "Run `python scripts/seed_dev_db.py` first."
        )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
