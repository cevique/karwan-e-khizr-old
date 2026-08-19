"""
API schemas for the journey-search endpoint (`POST /transit/journeys/search`).

Deliberately separate from `api/transit/schemas.py` (which stays focused
on the static Agency/Route/Stop API) - this module imports and reuses
`Coordinates`/`StopRead`/`RouteListItem`/`AgencyRead`/`RouteGeometryRead`
from there rather than duplicating equivalent structures, per this step's
explicit instruction.

Like the rest of the API layer, everything here is a plain Pydantic
`BaseModel` - never a `routing.journey`/`routing.graph` dataclass or a
SQLAlchemy model directly. `api/transit/journeys.py` is the only place
that maps between them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from api.transit.schemas import AgencyRead, Coordinates, RouteGeometryRead, RouteListItem, StopRead

# The routing objective to optimize for - kept as a plain Literal (not an
# enum) so an invalid value naturally produces a 422 from Pydantic without
# any extra validation code, matching how `objective` is validated
# everywhere else it's used.
RoutingObjective = Literal["fastest", "fewest_transfers", "least_walking"]

# Bound for the request's optional `max_walk_m` override. Consistent with
# `api/transit/router.py`'s `MAX_RADIUS_M` (also 20 km) for the same
# reason: comfortably covers any plausible walk-to-a-stop distance while
# still bounding how much of the stops table a single request can force
# PostGIS to scan (routing.snapping's own search radius, reused here).
MAX_MAX_WALK_M = 20_000.0


class JourneySearchRequest(BaseModel):
    """Request body for `POST /transit/journeys/search`."""

    origin: Coordinates
    destination: Coordinates
    objective: RoutingObjective = "fastest"
    max_walk_m: float | None = Field(
        None,
        gt=0,
        le=MAX_MAX_WALK_M,
        description=(
            "Override for how far a passenger is willing to walk to/from a "
            "stop, in meters. Defaults to routing.snapping.DEFAULT_MAX_WALK_M "
            "when omitted."
        ),
    )
    departure_time: datetime | None = Field(
        None,
        description=(
            "Accepted for forward compatibility with future schedule-aware "
            "routing (Trip/StopTime data does not exist yet). Currently has "
            "NO effect on the search: routing is entirely schedule-agnostic "
            "at this stage, so this value is accepted and validated but "
            "otherwise ignored."
        ),
    )


class WalkLegRead(BaseModel):
    """A walking segment of a journey: either origin-to-stop,
    stop-to-stop (a transfer), or stop-to-destination.

    `from_stop`/`to_stop` are `None` exactly when that end is the
    passenger's raw origin/destination point rather than a `Stop` - in
    that case `from_location`/`to_location` are the request's own
    `origin`/`destination` coordinates instead of a stop's. When the
    corresponding `*_stop` is present, `*_location` is simply that stop's
    own coordinates (so a client can always read `from_location`/
    `to_location` unconditionally to draw the leg, without checking which
    case applies).
    """

    type: Literal["walk"] = "walk"
    from_stop: StopRead | None
    to_stop: StopRead | None
    from_location: Coordinates
    to_location: Coordinates
    distance_m: float
    duration_s: float


class RideLegRead(BaseModel):
    """One uninterrupted ride on a single Route, with enough information
    for a client to render it: which route/agency, where to board and
    alight, and every stop passed through in between, in order.

    `route_geometry` (Phase 6, plan.md section H item 6) is the SAME
    shape `GET /transit/routes/{id}/geometry` returns for this leg's
    `route` - the route's FULL road-following polyline, not a sub-path
    cropped to just the boarded-to-alighted segment. Per
    `docs/MAP_AND_REALTIME_RECOMMENDATIONS.md` section B's own
    recommendation: the frontend already has `board_stop`/`alight_stop`/
    `intermediate_stops` in sequence order, so it can slice the polyline
    to the ridden segment itself if it wants to - cheaper and simpler on
    both sides than the backend computing and returning a sub-polyline.
    Null (`{type: null, coordinates: null, ...}`) exactly when the
    underlying `Route.path` hasn't been generated yet - the overwhelming
    majority of routes today (see the Phase 3 handoff) - never a
    fabricated or straight-line-substituted geometry.
    """

    type: Literal["ride"] = "ride"
    route: RouteListItem
    agency: AgencyRead
    board_stop: StopRead
    alight_stop: StopRead
    intermediate_stops: list[StopRead]
    duration_s: float
    route_geometry: RouteGeometryRead


JourneyLegRead = Annotated[WalkLegRead | RideLegRead, Field(discriminator="type")]


class JourneyRead(BaseModel):
    """A complete origin-to-destination journey.

    **`total_duration_s` is passenger-facing total elapsed time,
    INCLUDING transfer penalty time** (`transfer_count *
    routing.config.TRANSFER_PENALTY_S`) - this is deliberately different
    from `routing.journey.Journey.total_duration_s`, which is the sum of
    actual walk/ride durations only (see that dataclass's own docstring
    for why). The adjustment is applied once, at the API boundary
    (`api/transit/journeys.py`), the same way regardless of which
    `objective` produced the journey - specifically so a "fastest"
    journey's reported duration doesn't quietly exclude the transfer time
    the optimizer actually weighed when choosing this path, and so a
    `least_walking`/`fewest_transfers` journey's duration is reported on
    the same passenger-facing basis even though neither of those
    objectives adds the penalty internally while searching (see
    `routing.search`) - the internal `Journey`'s pure semantics are left
    alone rather than corrupted to match this API-level presentation
    choice.
    """

    objective: RoutingObjective
    total_duration_s: float
    total_walk_m: float
    transfer_count: int
    legs: list[JourneyLegRead]


class JourneySearchResponse(BaseModel):
    """Response body for `POST /transit/journeys/search`.

    `journeys` is a list for future extensibility (e.g. alternative
    itineraries), but this MVP's single-path Dijkstra search returns at
    most one - either exactly one journey, or an empty list when
    candidate stops exist near both the origin and destination but no
    transit path connects them (a legitimate, successful "no route
    exists" result - see `api/transit/journeys.py`'s docstring - NOT an
    HTTP error).
    """

    journeys: list[JourneyRead]
