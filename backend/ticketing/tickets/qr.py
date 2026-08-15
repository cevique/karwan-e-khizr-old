"""
QR ticket payload: a deterministic, verifiable, opaque string the backend
signs and the frontend renders as a QR code with its own QR library (no
QR *image* is generated server-side - see this module's docstring section
below for why).

Design
------
The payload is a compact JWT (HS256, signed with the application's own
`SECRET_KEY` - the same key `users/security.py` uses for access tokens,
but with a different `type` claim so one can never be presented as the
other). It contains only:

    tid   - the ticket's UUID
    uid   - the ticket owner's UUID (so a validator's device can display
            *whose* ticket this is without an extra lookup)
    type  - "ticket_qr" (see above)
    iat   - issued-at

No fare amount, no personal data beyond the two UUIDs, and - deliberately
- no `exp`/expiry claim enforced by the token itself. The server remains
authoritative over whether a ticket is currently valid: `verify_qr_payload`
only proves the payload is authentic (was issued by this backend and has
not been tampered with) and extracts `tid`/`uid`; the actual "is this
ticket still active, unexpired, not revoked, not already used" decision
is always made from the live `Ticket` row in the database (see
`ticketing.tickets.service.validate_ticket`), never from anything in the
token. This matters concretely: it means revoking a ticket or marking it
used takes effect immediately, even though the QR image on the
passenger's phone is static and can't be un-rendered.

A ticket ID alone is intentionally not sufficient to validate/inspect a
ticket - see api/tickets/router.py's `POST /api/tickets/validate`, which
takes this signed payload, not a raw `ticket_id` - so a validator client
can't be handed a guessable identifier and treat it as proof of a real
ticket.

Why not an actual QR *image*
-----------------------------
Generating a QR image server-side would add a dependency (e.g. `qrcode`)
and a binary-response code path for no real benefit: any frontend QR
library can render an opaque string just as well, and returning the raw
string keeps this endpoint a plain JSON response like everything else in
this workstream's API.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import jwt

from core.config import settings

_ALGORITHM = "HS256"
_QR_TOKEN_TYPE = "ticket_qr"


class InvalidQrPayloadError(Exception):
    """Raised for any structurally-invalid, unsigned/tampered, or
    wrong-type QR payload."""


@dataclass(frozen=True)
class QrClaims:
    ticket_id: uuid.UUID
    user_id: uuid.UUID


def build_qr_payload(*, ticket_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """Build the signed QR payload string for a ticket."""
    payload = {
        "tid": str(ticket_id),
        "uid": str(user_id),
        "type": _QR_TOKEN_TYPE,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def verify_qr_payload(token: str) -> QrClaims:
    """Verify the payload's signature and shape, returning the embedded
    `tid`/`uid`. Raises `InvalidQrPayloadError` on any failure.

    Deliberately does NOT enforce an expiry from the token itself (see
    this module's docstring) - `verify_exp=False` here means "this
    signature is authentic", full stop; the caller (
    `ticketing.tickets.service.validate_ticket`) is responsible for
    checking the live `Ticket.valid_until`/`status` from the database.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[_ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.PyJWTError as exc:
        raise InvalidQrPayloadError(str(exc)) from exc

    if payload.get("type") != _QR_TOKEN_TYPE:
        raise InvalidQrPayloadError("not a ticket QR payload")

    try:
        ticket_id = uuid.UUID(str(payload.get("tid")))
        user_id = uuid.UUID(str(payload.get("uid")))
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidQrPayloadError("malformed payload") from exc

    return QrClaims(ticket_id=ticket_id, user_id=user_id)
