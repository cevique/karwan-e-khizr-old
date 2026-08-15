"""
Tickets API: purchase, list, get, validate, revoke.

All endpoints except `POST /validate` require an authenticated,
active passenger and only ever operate on that user's own tickets
(`ticketing.tickets.service.get_ticket_for_user` enforces ownership -
see its docstring for why a not-yours ticket 404s instead of 403ing).
`POST /validate` instead requires a "validator"/"admin" role (see
`users.dependencies.require_role`) and operates on whichever ticket the
signed QR payload identifies.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.ticket import Ticket
from db.models.user import VALIDATOR_ROLES, User
from db.session import get_session
from ticketing.tickets.qr import InvalidQrPayloadError, verify_qr_payload
from ticketing.tickets.schemas import (
    TicketPurchaseRequest,
    TicketRead,
    TicketValidateRequest,
    TicketValidateResponse,
)
from ticketing.tickets.service import (
    PaymentFailedError,
    TicketNotFoundError,
    TicketOwnershipError,
    build_qr_payload_for,
    create_ticket,
    get_ticket_for_user,
    list_user_tickets,
    revoke_ticket,
    validate_ticket,
)
from users.dependencies import get_current_active_user, require_role

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _to_ticket_read(ticket: Ticket) -> TicketRead:
    """Build the API representation of `ticket`, including a freshly
    (re)signed QR payload - see ticketing/tickets/qr.py's docstring for
    why the payload isn't itself a stored column."""
    return TicketRead(
        id=ticket.id,
        ticket_code=ticket.ticket_code,
        status=ticket.status,
        fare_amount=str(ticket.fare_amount),
        currency=ticket.currency,
        objective=ticket.objective,
        origin_lat=ticket.origin_lat,
        origin_lon=ticket.origin_lon,
        destination_lat=ticket.destination_lat,
        destination_lon=ticket.destination_lon,
        ride_leg_count=ticket.ride_leg_count,
        transfer_count=ticket.transfer_count,
        total_duration_s=ticket.total_duration_s,
        total_walk_m=ticket.total_walk_m,
        route_summary=ticket.route_summary,
        valid_from=ticket.valid_from,
        valid_until=ticket.valid_until,
        used_at=ticket.used_at,
        revoked_at=ticket.revoked_at,
        created_at=ticket.created_at,
        qr_payload=build_qr_payload_for(ticket),
    )


@router.post("", response_model=TicketRead, status_code=status.HTTP_201_CREATED)
async def purchase_ticket(
    body: TicketPurchaseRequest,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> TicketRead:
    try:
        ticket = await create_ticket(session, user=user, request_journey=body.journey)
    except PaymentFailedError:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Payment was not successful"
        ) from None

    await session.commit()
    return _to_ticket_read(ticket)


@router.get("", response_model=list[TicketRead])
async def list_my_tickets(
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[TicketRead]:
    tickets = await list_user_tickets(session, user=user)
    await session.commit()
    return [_to_ticket_read(t) for t in tickets]


@router.get("/{ticket_id}", response_model=TicketRead)
async def get_ticket(
    ticket_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> TicketRead:
    try:
        ticket = await get_ticket_for_user(session, user=user, ticket_id=ticket_id)
    except (TicketNotFoundError, TicketOwnershipError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found") from None

    await session.commit()
    return _to_ticket_read(ticket)


@router.post("/{ticket_id}/revoke", response_model=TicketRead)
async def revoke_my_ticket(
    ticket_id: uuid.UUID,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_session),
) -> TicketRead:
    try:
        ticket = await revoke_ticket(session, user=user, ticket_id=ticket_id)
    except (TicketNotFoundError, TicketOwnershipError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None

    await session.commit()
    return _to_ticket_read(ticket)


@router.post("/validate", response_model=TicketValidateResponse)
async def validate(
    body: TicketValidateRequest,
    validator: User = Depends(require_role(*VALIDATOR_ROLES)),
    session: AsyncSession = Depends(get_session),
) -> TicketValidateResponse:
    try:
        claims = verify_qr_payload(body.qr_payload)
    except InvalidQrPayloadError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed or forged QR payload"
        ) from None

    result = await validate_ticket(
        session, ticket_id=claims.ticket_id, qr_user_id=claims.user_id, validator=validator
    )
    await session.commit()

    return TicketValidateResponse(
        valid=result.valid,
        reason=result.reason,
        ticket=_to_ticket_read(result.ticket) if result.ticket is not None else None,
    )
