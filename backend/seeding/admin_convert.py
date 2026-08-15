"""
Convert the admin/dev API's Pydantic request body into the plain
`seeding.import_schema.ImportDataset` that `seeding.validation`/
`seeding.importer` actually operate on.

Lives in `seeding/` (not `api/admin/`) so both `api/admin/router.py`
(`POST /admin/import`) and `api/dev/router.py` (`POST /dev/validate`)
share exactly one conversion instead of two copies drifting apart - both
routers' request bodies have the identical shape (`api.dev.schemas.
ValidateRequest` is literally `api.admin.schemas.ImportRequest`, unchanged
- see that module).

Takes a duck-typed `payload` (anything with `.agencies`/`.stops`/
`.routes`/`.route_stops` list attributes matching `api.admin.schemas.
ImportRequest`'s shape) rather than importing that Pydantic model here,
so this module - like the rest of `seeding/` - has no FastAPI/Pydantic
import of its own.
"""

from __future__ import annotations

from typing import Protocol

from seeding.import_schema import (
    ImportAgency,
    ImportDataset,
    ImportRoute,
    ImportRouteStop,
    ImportStop,
)


class _ImportPayloadLike(Protocol):
    agencies: list
    stops: list
    routes: list
    route_stops: list


def to_import_dataset(payload: _ImportPayloadLike) -> ImportDataset:
    return ImportDataset(
        agencies=tuple(
            ImportAgency(name=a.name, network_type=a.network_type)
            for a in payload.agencies
        ),
        stops=tuple(
            ImportStop(ref=s.ref, name=s.name, latitude=s.latitude, longitude=s.longitude)
            for s in payload.stops
        ),
        routes=tuple(
            ImportRoute(
                ref=r.ref,
                agency=r.agency,
                short_name=r.short_name,
                long_name=r.long_name,
                color=r.color,
            )
            for r in payload.routes
        ),
        route_stops=tuple(
            ImportRouteStop(
                route_ref=rs.route_ref,
                stop_ref=rs.stop_ref,
                sequence=rs.sequence,
                distance_along_route_m=rs.distance_along_route_m,
            )
            for rs in payload.route_stops
        ),
    )
