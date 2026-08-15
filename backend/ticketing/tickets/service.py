"""
Ticket lifecycle: purchase, listing, ownership-checked lookup, validation,
and revocation.

Expiry is checked lazily (at read/validate time), not by a background
job: any ticket whose `valid_until` has passed and whose status is still
`STATUS_ACTIVE` is transitioned to `STATUS_EXPIRED` the next time it's
looked at (`_apply_lazy_expiry`), then that updated status is what's
returned/used. This is a hackathon-appropriate simplification - a
scheduled sweep would keep the `status` column accurate even for tickets
nobody looks at again, but nothing in this system depends on that (every
read path already re-derives the effective state).
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ticket import (
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_REVOKED,
    STATUS_USED,
    Ticket,
)
from db.models.user import User
from ticketing.fares.schemas import JourneySummaryIn
from ticketing.fares.service import calculate_fare
from ticketing.payments.provider import DevPaymentProvider, PaymentProvider
from ticketing.tickets.config import (
    TICKET_CODE_ALPHABET,
    TICKET_CODE_LENGTH,
    TICKET_VALIDITY_MINUTES,
)
from ticketing.tickets.qr import build_qr_payload

# The only PaymentProvider wired up for this workstream - see
# ticketing/payments/provider.py's docstring. A real provider would be
# swapped in here (or injected) without changing anything below it.
_payment_provider: PaymentProvider = DevPaymentProvider()


class TicketNotFoundError(Exception):
    pass


class TicketOwnershipError(Exception):
    """Raised when a user tries to access a ticket that isn't theirs."""


class PaymentFailedError(Exception):
    pass


def _generate_ticket_code() -> str:
    return "".join(secrets.choice(TICKET_CODE_ALPHABET) for _ in range(TICKET_CODE_LENGTH))


def _apply_lazy_expiry(ticket: Ticket) -> Ticket:
    """Transition `ticket` to STATUS_EXPIRED in-place if it's still
    STATUS_ACTIVE but past `valid_until`. Caller is responsible for
    flushing/committing if this mutation should persist."""
    if ticket.status == STATUS_ACTIVE and ticket.valid_until < datetime.now(timezone.utc):
        ticket.status = STATUS_EXPIRED
    return ticket


async def create_ticket(
    session: AsyncSession, *, user: User, request_journey: JourneySummaryIn
) -> Ticket:
    """Purchase a ticket for `user` covering `request_journey`.

    The fare is always recomputed server-side (`calculate_fare`), never
    taken from the client. Payment goes through the configured
    `PaymentProvider` (currently always `DevPaymentProvider`, which never
    represents a real transaction - see that module's docstring); a
    failed charge raises `PaymentFailedError` and no `Ticket` row is
    created. Does not commit - the caller (the API route) commits.
    """
    quote = await calculate_fare(session, request_journey)

    payment = await _payment_provider.charge(
        user_id=user.id, amount=quote.amount, currency=quote.currency
    )
    if not payment.success:
        raise PaymentFailedError(
            f"payment via provider {payment.provider_name!r} was not successful"
        )

    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(minutes=TICKET_VALIDITY_MINUTES)

    ticket = Ticket(
        ticket_code=_generate_ticket_code(),
        user_id=user.id,
        status=STATUS_ACTIVE,
        fare_amount=quote.amount,
        currency=quote.currency,
        objective=request_journey.objective,
        origin_lat=request_journey.origin_latitude,
        origin_lon=request_journey.origin_longitude,
        destination_lat=request_journey.destination_latitude,
        destination_lon=request_journey.destination_longitude,
        ride_leg_count=len(request_journey.ride_legs),
        transfer_count=request_journey.transfer_count,
        total_duration_s=request_journey.total_duration_s,
        total_walk_m=request_journey.total_walk_m,
        route_summary=[leg.route_short_name for leg in request_journey.ride_legs],
        valid_from=now,
        valid_until=valid_until,
    )
    session.add(ticket)

    # Extremely unlikely, but `ticket_code` is unique - retry once with a
    # fresh code on a collision rather than surfacing a raw IntegrityError
    # to the caller.
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        ticket.ticket_code = _generate_ticket_code()
        session.add(ticket)
        await session.flush()

    return ticket


async def list_user_tickets(session: AsyncSession, *, user: User) -> list[Ticket]:
    result = await session.execute(
        select(Ticket).where(Ticket.user_id == user.id).order_by(Ticket.created_at.desc())
    )
    tickets = list(result.scalars().all())
    for ticket in tickets:
        _apply_lazy_expiry(ticket)
    await session.flush()
    return tickets


async def get_ticket_for_user(
    session: AsyncSession, *, user: User, ticket_id: uuid.UUID
) -> Ticket:
    """Fetch `ticket_id`, enforcing that it belongs to `user`.

    Raises `TicketNotFoundError` if no such ticket exists at all, and
    `TicketOwnershipError` if it exists but belongs to someone else -
    callers map these to 404 either way (see api/tickets/router.py) so a
    caller can't distinguish "not found" from "not yours" by response
    shape.
    """
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise TicketNotFoundError(str(ticket_id))
    if ticket.user_id != user.id:
        raise TicketOwnershipError(str(ticket_id))
    _apply_lazy_expiry(ticket)
    await session.flush()
    return ticket


async def revoke_ticket(session: AsyncSession, *, user: User, ticket_id: uuid.UUID) -> Ticket:
    """Cancel a ticket. Only the owner may revoke their own ticket, and
    only while it's still STATUS_ACTIVE (an already-used/expired/revoked
    ticket can't be revoked - there'd be nothing left to prevent)."""
    ticket = await get_ticket_for_user(session, user=user, ticket_id=ticket_id)
    if ticket.status != STATUS_ACTIVE:
        raise ValueError(f"cannot revoke a ticket with status {ticket.status!r}")
    ticket.status = STATUS_REVOKED
    ticket.revoked_at = datetime.now(timezone.utc)
    await session.flush()
    return ticket


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str | None
    ticket: Ticket | None


async def validate_ticket(
    session: AsyncSession, *, ticket_id: uuid.UUID, qr_user_id: uuid.UUID, validator: User
) -> ValidationResult:
    """Validate and, if currently active, consume a ticket.

    `ticket_id`/`qr_user_id` come from an already signature-verified QR
    payload (see ticketing.tickets.qr.verify_qr_payload) - this function
    is the authoritative check of the ticket's *current* state, entirely
    from the database, per that module's docstring. On success (a
    currently-active, unexpired ticket), the ticket is marked
    STATUS_USED and consumed - a ticket can only ever be validated once.
    """
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        return ValidationResult(valid=False, reason="ticket not found", ticket=None)

    if ticket.user_id != qr_user_id:
        # The signature was authentic, but its claimed owner doesn't
        # match the ticket's actual owner - the payload has been
        # tampered with or reassembled from two different tickets.
        return ValidationResult(valid=False, reason="ticket owner mismatch", ticket=None)

    _apply_lazy_expiry(ticket)

    if ticket.status == STATUS_REVOKED:
        await session.flush()
        return ValidationResult(valid=False, reason="ticket has been revoked", ticket=ticket)
    if ticket.status == STATUS_USED:
        await session.flush()
        return ValidationResult(valid=False, reason="ticket has already been used", ticket=ticket)
    if ticket.status == STATUS_EXPIRED:
        await session.flush()
        return ValidationResult(valid=False, reason="ticket has expired", ticket=ticket)

    # STATUS_ACTIVE and not expired - consume it.
    ticket.status = STATUS_USED
    ticket.used_at = datetime.now(timezone.utc)
    ticket.validated_by = validator.id
    await session.flush()
    return ValidationResult(valid=True, reason=None, ticket=ticket)


def build_qr_payload_for(ticket: Ticket) -> str:
    """Build the QR payload string for `ticket` - a thin wrapper kept
    here (rather than calling ticketing.tickets.qr directly from the API
    layer) so every caller building a `TicketRead` goes through the same
    place."""
    return build_qr_payload(ticket_id=ticket.id, user_id=ticket.user_id)
