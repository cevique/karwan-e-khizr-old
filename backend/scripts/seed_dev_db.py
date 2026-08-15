#!/usr/bin/env python3
"""
Apply or reset the deterministic demo dataset (`data.seed_dataset`)
against the database configured by `DATABASE_URL`.

Run from the `backend/` directory:

    python scripts/seed_dev_db.py                  # insert (default)
    python scripts/seed_dev_db.py --mode replace    # replace
    python scripts/seed_dev_db.py --reset           # delete seed rows only
    python scripts/seed_dev_db.py --status          # report presence only

Uses the existing `db.session.AsyncSessionLocal` (the same session
factory the application itself uses) - no separate engine or connection
logic lives here. This is a thin CLI wrapper around `seeding.seed`; the
same operations are also available over HTTP via the admin API once it's
wired into a running application (see `backend/data/README.md`).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def _run(args: argparse.Namespace) -> None:
    from db.session import AsyncSessionLocal
    from seeding.seed import clear_seed_data, get_seed_status, seed_database

    async with AsyncSessionLocal() as session:
        if args.status:
            status = await get_seed_status(session)
            for key, value in status.items():
                print(f"{key}: {value}")
            return

        if args.reset:
            await clear_seed_data(session)
            print("Seed dataset rows removed (by deterministic ID only).")
            return

        report = await seed_database(session, mode=args.mode)
        print(f"mode: {report.mode}")
        print(
            f"agencies:    created={report.agencies_created:>3} "
            f"skipped={report.agencies_skipped:>3}"
        )
        print(
            f"stops:       created={report.stops_created:>3} "
            f"skipped={report.stops_skipped:>3}"
        )
        print(
            f"routes:      created={report.routes_created:>3} "
            f"skipped={report.routes_skipped:>3}"
        )
        print(
            f"route_stops: created={report.route_stops_created:>3} "
            f"skipped={report.route_stops_skipped:>3}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--mode",
        choices=("insert", "replace"),
        default="insert",
        help="Seed mode (default: insert). Ignored with --reset/--status.",
    )
    group.add_argument(
        "--reset", action="store_true", help="Delete seed dataset rows and exit."
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="Report how much of the seed dataset is present and exit.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
