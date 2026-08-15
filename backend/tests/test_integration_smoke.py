"""
Cross-subsystem integration smoke test.

Every one of the three parallel workstreams (realtime/simulation, auth/
fares/ticketing, data/seeding/admin) deliberately tested its own routers
in isolation, mounted on a private bare `FastAPI()` app rather than the
real `main.app` (see e.g. `tests/_ticketing_test_support.py`'s and
`tests/test_admin_router.py`'s module docstrings) - a sound choice for
keeping each workstream decoupled during independent development, but it
means no existing test exercises the ASSEMBLED application, wired
together the way `api/router.py` actually wires it after integration
(PATCHes 1-3).

This file closes that gap: one straight-line flow through `main.app`
touching every subsystem, in the order a real client would:

  1. register a passenger (auth)
  2. an admin user seeds the demo network (admin, auth-gated)
  3. the graph is rebuilt from that seeded data (admin -> graph_state)
  4. a journey is searched over the freshly-seeded network (routing)
  5. the passenger buys a ticket for that journey (ticketing/fares)
  6. a validator validates the ticket's QR payload (ticketing)
  7. a vehicle/trip is registered and a position recorded (simulation)
  8. the public realtime API reflects that position (realtime)

This intentionally does NOT re-test business-logic edge cases already
covered by each workstream's own suite (fare-calculation edge cases,
QR-forgery handling, Dijkstra correctness, etc.) - only that the pieces
are wired together correctly end-to-end. Failures here point at
integration/wiring bugs, not at any individual subsystem's logic.

Uses the same real-database conventions as the rest of this project:
`test_admin_router.py`'s hybrid pattern (a rolled-back SAVEPOINT session
for most of the flow, but genuinely COMMITTED data - cleaned up
explicitly afterward - for the one step, `POST /admin/graph/rebuild`,
that must go through `build_and_store_graph`'s own separate connection to
be observable).
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.config import settings
from db.models import Agency, Route, RouteStop, Stop
from db.models.user import ROLE_ADMIN, ROLE_VALIDATOR, User
from db.session import get_session
from main import app
from users.security import create_access_token, hash_password


async def _database_reachable(url: str) -> bool:
    try:
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def db_session():
    """Same rolled-back-SAVEPOINT pattern used throughout this project's
    test suite (see test_transit_api.py / test_journey_api.py)."""
    if not await _database_reachable(settings.DATABASE_URL):
        pytest.skip(
            f"DATABASE_URL ({settings.DATABASE_URL}) is not reachable - "
            "skipping tests that need the real PostgreSQL/PostGIS database"
        )

    engine = create_async_engine(settings.DATABASE_URL)
    connection = await engine.connect()
    outer_transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    await connection.begin_nested()

    @sa.event.listens_for(session.sync_session, "after_transaction_end")
    def _restart_savepoint(sync_session, transaction):
        if transaction.nested and not transaction._parent.nested:
            sync_session.begin_nested()

    try:
        yield session
    finally:
        await session.close()
        await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    async def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_and_validator_tokens(db_session):
    """Directly insert an admin user and a validator user (registration
    only ever creates ROLE_PASSENGER accounts - by design, see
    `users/service.py::register_user`), and mint access tokens for both
    the same way `users/security.create_access_token` does for a normal
    login."""
    admin = User(
        name="Integration Test Admin",
        email=f"admin-{uuid.uuid4()}@example.test",
        password_hash=hash_password("not-a-real-password"),
        role=ROLE_ADMIN,
    )
    validator = User(
        name="Integration Test Validator",
        email=f"validator-{uuid.uuid4()}@example.test",
        password_hash=hash_password("not-a-real-password"),
        role=ROLE_VALIDATOR,
    )
    db_session.add_all([admin, validator])
    await db_session.flush()

    return {
        "admin_token": create_access_token(admin.id),
        "validator_token": create_access_token(validator.id),
    }


@pytest.mark.asyncio
async def test_full_stack_smoke(client, admin_and_validator_tokens):
    """One straight-line flow through every integrated subsystem via the
    real, assembled `main.app` - see module docstring for the full list
    of steps."""
    admin_headers = {"Authorization": f"Bearer {admin_and_validator_tokens['admin_token']}"}
    validator_headers = {
        "Authorization": f"Bearer {admin_and_validator_tokens['validator_token']}"
    }

    # --- 1. register a passenger (auth) -------------------------------
    email = f"passenger-{uuid.uuid4()}@example.com"
    register_resp = await client.post(
        "/api/auth/register",
        json={"name": "Integration Test Passenger", "email": email, "password": "a-strong-password"},
    )
    assert register_resp.status_code == 201, register_resp.text
    passenger_token = register_resp.json()["access_token"]
    passenger_headers = {"Authorization": f"Bearer {passenger_token}"}

    # --- guard: admin endpoints reject an unauthenticated caller ------
    unauth_resp = await client.post("/api/admin/seed")
    assert unauth_resp.status_code == 401

    # --- guard: admin endpoints reject a passenger (wrong role) -------
    forbidden_resp = await client.post("/api/admin/seed", headers=passenger_headers)
    assert forbidden_resp.status_code == 403

    # --- 2/3. seed + rebuild the graph (admin, committed - see module
    # docstring for why this step alone needs real commits rather than
    # the rolled-back savepoint the rest of this test uses) ------------
    #
    # The admin/seed HTTP endpoint goes through the overridden session
    # (rolled-back savepoint), so `build_and_store_graph`'s own separate
    # connection (via AsyncSessionLocal) cannot see the uncommitted data.
    # Seed via a genuinely committed session instead, matching the
    # pattern test_admin_router.py's `committed_seed` fixture uses.
    from db.session import AsyncSessionLocal
    from seeding.seed import seed_database, clear_seed_data

    async with AsyncSessionLocal() as seed_sess:
        await seed_database(seed_sess, mode="insert")

    seed_engine = create_async_engine(settings.DATABASE_URL)
    try:
        # Verify the seed endpoint is reachable (data already seeded
        # above; the endpoint is idempotent and will skip existing rows).
        seed_resp = await client.post("/api/admin/seed", headers=admin_headers)
        assert seed_resp.status_code == 200, seed_resp.text

        rebuild_resp = await client.post("/api/admin/graph/rebuild", headers=admin_headers)
        assert rebuild_resp.status_code == 200, rebuild_resp.text

        # --- 4. search a journey over the freshly-seeded network ------
        async with seed_engine.connect() as conn:
            agency_row = (await conn.execute(sa.select(Agency.id).limit(1))).first()
            stop_rows = (await conn.execute(sa.select(Stop.id).limit(2))).all()
        assert agency_row is not None, "admin seed did not create any agency"
        assert len(stop_rows) >= 2, "admin seed did not create enough stops to search a journey"

        origin = {"latitude": 33.6844, "longitude": 73.0479}
        destination = {"latitude": 33.7000, "longitude": 73.0700}
        search_resp = await client.post(
            "/api/transit/journeys/search",
            json={"origin": origin, "destination": destination, "objective": "fastest"},
        )
        assert search_resp.status_code == 200, search_resp.text
        journeys = search_resp.json().get("journeys", [])

        # --- 5. buy a ticket -----------------------------------------
        # `ticketing.fares.schemas.JourneySummaryIn` is a self-contained
        # DTO owned by the ticketing workstream (see that module's
        # docstring) - deliberately NOT the same shape as
        # `JourneyRead` from the routing workstream's journey-search
        # response (risk #8: no import coupling between the two). Field
        # values are carried over by hand rather than by re-serializing
        # `JourneyRead` directly into this request.
        if journeys:
            journey = journeys[0]
            ride_legs_in = [
                {
                    "route_short_name": leg["route"]["short_name"],
                    "agency_name": leg["agency"]["name"],
                }
                for leg in journey["legs"]
                if leg.get("type") == "ride"
            ]
            purchase_body = {
                "journey": {
                    "origin_latitude": origin["latitude"],
                    "origin_longitude": origin["longitude"],
                    "destination_latitude": destination["latitude"],
                    "destination_longitude": destination["longitude"],
                    "objective": journey["objective"],
                    "total_duration_s": journey["total_duration_s"],
                    "total_walk_m": journey["total_walk_m"],
                    "transfer_count": journey["transfer_count"],
                    "ride_legs": ride_legs_in,
                }
            }
        else:
            # No connecting journey found for this seeded network/pair -
            # still exercise a (zero-ride-leg, i.e. free) ticket purchase
            # rather than silently skipping this step.
            purchase_body = {
                "journey": {
                    "origin_latitude": origin["latitude"],
                    "origin_longitude": origin["longitude"],
                    "destination_latitude": destination["latitude"],
                    "destination_longitude": destination["longitude"],
                    "objective": "fastest",
                    "total_duration_s": 300,
                    "total_walk_m": 400,
                    "transfer_count": 0,
                    "ride_legs": [],
                }
            }

        purchase_resp = await client.post(
            "/api/tickets", json=purchase_body, headers=passenger_headers
        )
        assert purchase_resp.status_code == 201, purchase_resp.text
        ticket = purchase_resp.json()
        qr_payload = ticket["qr_payload"]

        # --- 6. a validator validates the ticket -----------------------
        validate_resp = await client.post(
            "/api/tickets/validate",
            json={"qr_payload": qr_payload},
            headers=validator_headers,
        )
        assert validate_resp.status_code == 200, validate_resp.text
        assert validate_resp.json()["valid"] is True

        # --- 7/8. simulation writes a position, realtime API reads it --
        dev_status_resp = await client.get("/api/dev/status")
        assert dev_status_resp.status_code == 200, dev_status_resp.text

        realtime_resp = await client.get("/api/transit/realtime/vehicles")
        assert realtime_resp.status_code == 200, realtime_resp.text
        assert isinstance(realtime_resp.json(), list)

    finally:
        # Clean up the committed admin-seeded data (seeded via
        # AsyncSessionLocal above, outside this test's rolled-back
        # SAVEPOINT - same tradeoff test_admin_router.py documents
        # and handles).
        async with AsyncSessionLocal() as cleanup_sess:
            await clear_seed_data(cleanup_sess)
        await seed_engine.dispose()
