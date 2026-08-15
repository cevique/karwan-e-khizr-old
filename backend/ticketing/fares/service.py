"""
Fare calculation, kept deliberately simple and behind this one function so
the formula can evolve later (e.g. to a real distance-based model, once
real distance data exists) without touching any caller.

Formula, given a `JourneySummaryIn` with `n = len(ride_legs)`:

    n == 0  -> free (0). A journey that's entirely walking never boards a
               vehicle, so there's nothing to charge for.
    n >= 1  -> base_fare + per_leg_fare * (n - 1)

i.e. the active `FareRule.base_fare` covers the first ride leg, and each
additional leg (every transfer onto another route) adds `per_leg_fare`.
This is a flat, configurable per-boarding model - not real distance-based
pricing - because no reliable ride-distance data exists yet (see
ticketing/fares/config.py's docstring for why). It is intentionally
*not* keyed off `transfer_count`, to stay consistent even if some future
routing change lets a "journey" contain a ride leg that isn't preceded by
a walking transfer.
"""

from __future__ import annotations

import decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.fare import FareRule
from ticketing.fares.config import (
    DEFAULT_BASE_FARE,
    DEFAULT_CURRENCY,
    DEFAULT_FARE_RULE_NAME,
    DEFAULT_PER_LEG_FARE,
)
from ticketing.fares.schemas import FareQuoteResponse, JourneySummaryIn


class _DefaultFareRule:
    """Stand-in used when no `FareRule` row exists in the database yet -
    same attribute surface as the `FareRule` ORM model, so
    `calculate_fare` doesn't need a branch for "no rule configured"."""

    name = DEFAULT_FARE_RULE_NAME
    base_fare = DEFAULT_BASE_FARE
    per_leg_fare = DEFAULT_PER_LEG_FARE
    currency = DEFAULT_CURRENCY


async def get_active_fare_rule(session: AsyncSession) -> FareRule | _DefaultFareRule:
    """Return the active `FareRule`, or the built-in default if none is
    configured yet. If more than one row is (incorrectly) marked active,
    an arbitrary one is used - `is_active` uniqueness is an application
    convention here, not a database constraint (see db/models/fare.py)."""
    result = await session.execute(
        select(FareRule).where(FareRule.is_active.is_(True)).limit(1)
    )
    rule = result.scalar_one_or_none()
    return rule if rule is not None else _DefaultFareRule()


def _amount_for(rule: FareRule | _DefaultFareRule, ride_leg_count: int) -> decimal.Decimal:
    if ride_leg_count <= 0:
        return decimal.Decimal("0.00")
    amount = decimal.Decimal(rule.base_fare) + decimal.Decimal(rule.per_leg_fare) * (
        ride_leg_count - 1
    )
    return amount.quantize(decimal.Decimal("0.01"))


async def calculate_fare(
    session: AsyncSession, journey: JourneySummaryIn
) -> FareQuoteResponse:
    """Compute the fare for `journey` using the currently active
    `FareRule` (or the built-in default)."""
    rule = await get_active_fare_rule(session)
    ride_leg_count = len(journey.ride_legs)
    amount = _amount_for(rule, ride_leg_count)

    return FareQuoteResponse(
        amount=str(amount),
        currency=rule.currency,
        ride_leg_count=ride_leg_count,
        fare_rule_name=rule.name,
    )
