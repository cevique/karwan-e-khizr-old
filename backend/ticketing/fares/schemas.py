"""
Pydantic schemas for fares, including `JourneySummaryIn` - the small,
self-contained DTO this whole workstream uses to describe "the journey
being priced/ticketed".

`JourneySummaryIn` is deliberately NOT `api.transit.journey_schemas.
JourneyRead` (or any subset imported from it). This workstream must stay
independent of the routing/journeys workstream (owned by a different
parallel Claude instance) and must not import its internals or its API
schemas - see this module's own docstring reasoning and the top-level
instructions' "JOURNEY INTEGRATION" section. Instead, a client that has
just called `POST /api/transit/journeys/search` extracts these few fields
from the `JourneyRead` it received and submits them here. This is a
deliberately thin contract: enough to price and later display a receipt
for the journey, nothing that requires understanding routing internals.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RideLegSummaryIn(BaseModel):
    """Minimal, display-only description of one ride leg of the journey
    being priced/purchased - just enough for a receipt."""

    route_short_name: str = Field(..., min_length=1, max_length=50)
    agency_name: str = Field(..., min_length=1, max_length=255)


class JourneySummaryIn(BaseModel):
    """Client-submitted summary of a previously-searched journey (from
    `POST /api/transit/journeys/search`'s response), used both to quote a
    fare and, on purchase, to record a ticket's receipt.

    The server does not re-verify this summary against a live routing
    call (routing is owned by a different workstream and is not imported
    here) - see this module's docstring. It is trusted the same way any
    other client-submitted purchase-intent data is: the *fare* charged is
    always recomputed server-side from `FareRule` (see
    `ticketing.fares.service`), never taken from the client, so a client
    cannot under-report `ride_leg_count`/`transfer_count` to pay less.
    """

    origin_latitude: float = Field(..., ge=-90, le=90)
    origin_longitude: float = Field(..., ge=-180, le=180)
    destination_latitude: float = Field(..., ge=-90, le=90)
    destination_longitude: float = Field(..., ge=-180, le=180)

    objective: str = Field(..., min_length=1, max_length=30)
    total_duration_s: float = Field(..., ge=0)
    total_walk_m: float = Field(..., ge=0)
    transfer_count: int = Field(..., ge=0)

    # Ordered ride legs of the journey - empty for a pure-walking journey
    # (which is always free; see calculate_fare). `ride_leg_count` used
    # for fare calculation is simply `len(ride_legs)`, not a
    # separately-submitted number, so it can't be spoofed independent of
    # the legs actually listed.
    ride_legs: list[RideLegSummaryIn] = Field(default_factory=list)


class FareQuoteResponse(BaseModel):
    """Response body for `POST /api/fares/quote` (and embedded in a
    purchased ticket's response)."""

    amount: str
    currency: str
    ride_leg_count: int
    fare_rule_name: str
