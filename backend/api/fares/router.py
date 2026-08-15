"""
Fares API: quote a fare for a journey.

`POST /api/fares/quote` is intentionally unauthenticated (a passenger
should be able to see a price before logging in/registering) - see
`users.dependencies.get_optional_current_user` usage note below; it
doesn't currently change the quote, but is wired in for forward
compatibility (e.g. a future frequent-rider discount) without an API
shape change.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.user import User
from db.session import get_session
from ticketing.fares.schemas import FareQuoteResponse, JourneySummaryIn
from ticketing.fares.service import calculate_fare
from users.dependencies import get_optional_current_user

router = APIRouter(prefix="/fares", tags=["fares"])


@router.post("/quote", response_model=FareQuoteResponse)
async def quote_fare(
    journey: JourneySummaryIn,
    session: AsyncSession = Depends(get_session),
    _user: User | None = Depends(get_optional_current_user),
) -> FareQuoteResponse:
    return await calculate_fare(session, journey)
