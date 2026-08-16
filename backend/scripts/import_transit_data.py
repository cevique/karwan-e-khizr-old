#!/usr/bin/env python3
"""
Import the canonical `docs/transit_data.json` research dataset into the
database configured by `DATABASE_URL` (Phase 1 of `plan.md`).

Run from the `backend/` directory:

    python scripts/import_transit_data.py                     # import, service date = today
    python scripts/import_transit_data.py --service-date 2026-08-16
    python scripts/import_transit_data.py --dry-run           # validate only, no writes
    python scripts/import_transit_data.py --dataset path/to/transit_data.json

The importer is idempotent: static rows (agencies/stops/routes/
route_stops) are get-or-create, and pattern-generated Trip/StopTime rows
use deterministic UUIDv5 IDs derived from (route, direction, start time),
so re-importing the same dataset on the same service date replaces them
in place instead of duplicating them.

The service date is the calendar day the generated trips belong to (all
days of the week per the `daily_default` service calendar in
`transit_data.json`). Pass a fixed date for reproducible re-imports; the
default (today) is convenient for running the live simulator against
"today's" schedule.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

DEFAULT_DATASET = os.path.join(BACKEND_DIR, "docs", "transit_data.json")


async def _run(args: argparse.Namespace) -> None:
    from db.session import AsyncSessionLocal
    from seeding.importer import ImportValidationError, import_dataset
    from seeding.transit_data_importer import load_transit_data
    from seeding.validation import validate_dataset

    dataset = load_transit_data(args.dataset)
    result = validate_dataset(dataset, allow_routes_without_stops=True)
    print(
        f"dataset:  {len(dataset.agencies)} agencies, {len(dataset.stops)} stops, "
        f"{len(dataset.routes)} routes, {len(dataset.route_stops)} route_stops, "
        f"{len(dataset.trip_patterns)} trip patterns"
    )
    print(f"issues:   {len(result.errors)} error(s), {len(result.warnings)} warning(s)")
    for issue in result.warnings:
        print(f"  warning [{issue.code}] {issue.location}: {issue.message}")
    if result.errors:
        for issue in result.errors:
            print(f"  error   [{issue.code}] {issue.location}: {issue.message}")
        print("Import aborted: validation found error-level issues.")
        sys.exit(1)

    if args.dry_run:
        print("Dry run: validation passed, nothing written.")
        return

    async with AsyncSessionLocal() as session:
        try:
            report = await import_dataset(
                session,
                dataset,
                allow_routes_without_stops=True,
                service_date=args.service_date,
            )
        except ImportValidationError as exc:
            print("Import aborted: validation failed.")
            for issue in exc.result.errors:
                print(f"  error [{issue.code}] {issue.location}: {issue.message}")
            sys.exit(1)

    print(f"service_date: {args.service_date.isoformat()}")
    print(f"agencies:      created={report.agencies_created} updated={report.agencies_updated}")
    print(f"stops:         created={report.stops_created} updated={report.stops_updated}")
    print(f"routes:        created={report.routes_created} updated={report.routes_updated}")
    print(
        f"route_stops:   created={report.route_stops_created} "
        f"updated={report.route_stops_updated}"
    )
    print(
        f"trips:         created={report.trips_created} replaced={report.trips_replaced}"
    )
    print(f"stop_times:    created={report.stop_times_created}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=DEFAULT_DATASET,
        help=f"Path to transit_data.json (default: {DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--service-date",
        type=date.fromisoformat,
        default=date.today(),
        help="Service date for generated trips, YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the dataset and report issues without writing anything.",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()