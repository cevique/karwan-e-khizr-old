"""
Tests for ticketing/fares/service.py and api/fares/router.py.
"""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import decimal

import pytest

from db.models.fare import FareRule
from tests._ticketing_test_support import client, db_session  # noqa: F401
from ticketing.fares.schemas import JourneySummaryIn, RideLegSummaryIn
from ticketing.fares.service import calculate_fare


def _journey(ride_legs: list[RideLegSummaryIn], transfer_count: int = 0) -> JourneySummaryIn:
    return JourneySummaryIn(
        origin_latitude=33.6844,
        origin_longitude=73.0479,
        destination_latitude=33.7100,
        destination_longitude=73.0700,
        objective="fastest",
        total_duration_s=900.0,
        total_walk_m=350.0,
        transfer_count=transfer_count,
        ride_legs=ride_legs,
    )


def _leg(short_name: str = "T-1") -> RideLegSummaryIn:
    return RideLegSummaryIn(route_short_name=short_name, agency_name="Test Agency")


# ---------------------------------------------------------------------------
# Pure calculation logic (uses db_session only to read/insert FareRule rows)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pure_walking_journey_is_free_with_default_rule(db_session):
    quote = await calculate_fare(db_session, _journey(ride_legs=[]))
    assert quote.amount == "0.00"
    assert quote.ride_leg_count == 0


@pytest.mark.asyncio
async def test_single_leg_journey_uses_base_fare_with_default_rule(db_session):
    quote = await calculate_fare(db_session, _journey(ride_legs=[_leg()]))
    assert quote.ride_leg_count == 1
    # Default fallback rule: base_fare=50.00 (see ticketing/fares/config.py)
    assert quote.amount == "50.00"


@pytest.mark.asyncio
async def test_multi_leg_journey_adds_per_leg_fare_with_default_rule(db_session):
    quote = await calculate_fare(db_session, _journey(ride_legs=[_leg("A"), _leg("B")]))
    assert quote.ride_leg_count == 2
    # base_fare (50.00) + 1 * per_leg_fare (20.00)
    assert quote.amount == "70.00"


@pytest.mark.asyncio
async def test_calculate_fare_uses_active_fare_rule_from_database(db_session):
    # Deactivate any pre-existing active rule (e.g. the migration-seeded
    # "default" row) within this rolled-back transaction, so this test's
    # own "promo" rule is unambiguously the only active one.
    from sqlalchemy import select

    existing = (await db_session.execute(select(FareRule))).scalars().all()
    for rule in existing:
        rule.is_active = False
    await db_session.flush()

    db_session.add(
        FareRule(
            name="promo",
            base_fare=decimal.Decimal("10.00"),
            per_leg_fare=decimal.Decimal("5.00"),
            currency="USD",
            is_active=True,
        )
    )
    await db_session.flush()

    quote = await calculate_fare(db_session, _journey(ride_legs=[_leg("A"), _leg("B"), _leg("C")]))
    assert quote.fare_rule_name == "promo"
    assert quote.currency == "USD"
    # 10.00 + 2 * 5.00
    assert quote.amount == "20.00"


@pytest.mark.asyncio
async def test_calculate_fare_ignores_inactive_fare_rule(db_session):
    db_session.add(
        FareRule(
            name="inactive-promo",
            base_fare=decimal.Decimal("1.00"),
            per_leg_fare=decimal.Decimal("1.00"),
            currency="USD",
            is_active=False,
        )
    )
    await db_session.flush()

    quote = await calculate_fare(db_session, _journey(ride_legs=[_leg()]))
    # Falls back to whatever other active rule exists (here, the
    # migration-seeded "default" row, or the built-in default if none
    # exists) - never the inactive USD rule just inserted.
    assert quote.currency == "PKR"
    assert quote.amount == "50.00"


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quote_endpoint_is_unauthenticated(client):
    response = await client.post(
        "/api/fares/quote",
        json=_journey(ride_legs=[_leg()]).model_dump(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["amount"] == "50.00"
    assert body["ride_leg_count"] == 1


@pytest.mark.asyncio
async def test_quote_endpoint_rejects_invalid_coordinates(client):
    payload = _journey(ride_legs=[]).model_dump()
    payload["origin_latitude"] = 200.0  # out of range
    response = await client.post("/api/fares/quote", json=payload)
    assert response.status_code == 422
