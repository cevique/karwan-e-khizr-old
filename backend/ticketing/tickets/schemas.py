"""Pydantic schemas for tickets. Never a raw ORM `Ticket` is returned."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ticketing.fares.schemas import JourneySummaryIn


class TicketPurchaseRequest(BaseModel):
    """Request body for `POST /api/tickets`.

    `journey` is the same `JourneySummaryIn` used for `POST
    /api/fares/quote` - see that schema's docstring for why it's a
    self-contained DTO rather than the routing workstream's `JourneyRead`.
    The fare actually charged is always recomputed server-side from it
    (see ticketing.fares.service.calculate_fare), never trusted from the
    client.
    """

    journey: JourneySummaryIn


class TicketRead(BaseModel):
    """Public representation of a Ticket - includes `qr_payload` (the
    signed, opaque string the frontend renders as a QR code) but never
    anything a validator/other party shouldn't see (no other user's
    data, no internal secrets)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_code: str
    status: str
    fare_amount: str
    currency: str

    objective: str
    origin_lat: float
    origin_lon: float
    destination_lat: float
    destination_lon: float
    ride_leg_count: int
    transfer_count: int
    total_duration_s: float | None
    total_walk_m: float | None
    route_summary: list[str] | None

    valid_from: datetime
    valid_until: datetime
    used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    # Not a persisted column - built fresh from the ticket's id/user_id
    # every time it's serialized (see api/tickets/router.py), so it's
    # always signed with the currently-configured SECRET_KEY.
    qr_payload: str


class TicketValidateRequest(BaseModel):
    """Request body for `POST /api/tickets/validate`. Takes the QR
    payload (not a raw `ticket_id`) - see ticketing/tickets/qr.py's
    docstring for why a bare ID must not be sufficient."""

    qr_payload: str = Field(..., min_length=1)


class TicketValidateResponse(BaseModel):
    """Response body for `POST /api/tickets/validate`.

    Always 200 (never 4xx) for a *structurally valid, signature-authentic*
    request - "this ticket is not valid right now" is a normal validation
    outcome (`valid=False` + `reason`), not an error. A 4xx is reserved
    for a malformed/forged payload (see api/tickets/router.py)."""

    valid: bool
    reason: str | None = None
    ticket: TicketRead | None = None
