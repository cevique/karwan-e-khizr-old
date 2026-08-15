"""
Tests for the tickets API (api/tickets/router.py) and
ticketing/tickets/service.py.
"""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from db.models.ticket import Ticket
from db.models.user import ROLE_VALIDATOR, User
from tests._ticketing_test_support import client, db_session  # noqa: F401
from ticketing.tickets.qr import build_qr_payload
from users.security import hash_password


def _unique_email() -> str:
    return f"user-{uuid.uuid4()}@example.com"


def _journey_payload(num_legs: int = 1) -> dict:
    return {
        "origin_latitude": 33.6844,
        "origin_longitude": 73.0479,
        "destination_latitude": 33.7100,
        "destination_longitude": 73.0700,
        "objective": "fastest",
        "total_duration_s": 900.0,
        "total_walk_m": 350.0,
        "transfer_count": max(num_legs - 1, 0),
        "ride_legs": [
            {"route_short_name": f"T-{i+1}", "agency_name": "Test Agency"}
            for i in range(num_legs)
        ],
    }


async def _register(client, name: str = "Passenger") -> tuple[str, dict]:
    response = await client.post(
        "/api/auth/register",
        json={"name": name, "email": _unique_email(), "password": "correct-horse-battery"},
    )
    assert response.status_code == 201
    body = response.json()
    return body["access_token"], body["user"]


async def _register_validator(db_session, client) -> str:
    """Create a "validator"-role user directly in the DB (self-registration
    can never produce one - see users/service.py::register_user) and log
    them in through the real API to get a real token."""
    email = _unique_email()
    password = "correct-horse-battery"
    db_session.add(
        User(name="Inspector", email=email, password_hash=hash_password(password), role=ROLE_VALIDATOR)
    )
    await db_session.flush()

    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


# ---------------------------------------------------------------------------
# Purchase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_purchase_ticket_requires_authentication(client):
    response = await client.post("/api/tickets", json={"journey": _journey_payload()})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_purchase_ticket_returns_ticket_with_qr_payload(client):
    token, _ = await _register(client)
    response = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload(num_legs=2)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "active"
    assert body["ride_leg_count"] == 2
    assert body["fare_amount"] == "70.00"  # 50.00 base + 1 * 20.00 per leg
    assert body["qr_payload"]
    assert body["route_summary"] == ["T-1", "T-2"]
    assert body["ticket_code"]


@pytest.mark.asyncio
async def test_purchase_pure_walking_journey_is_free(client):
    token, _ = await _register(client)
    response = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload(num_legs=0)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    assert response.json()["fare_amount"] == "0.00"


# ---------------------------------------------------------------------------
# Listing / ownership
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tickets_requires_authentication(client):
    response = await client.get("/api/tickets")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_tickets_only_returns_own_tickets(client):
    token_a, _ = await _register(client, "Alice")
    token_b, _ = await _register(client, "Bob")

    await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    response_a = await client.get("/api/tickets", headers={"Authorization": f"Bearer {token_a}"})
    response_b = await client.get("/api/tickets", headers={"Authorization": f"Bearer {token_b}"})

    assert response_a.status_code == response_b.status_code == 200
    assert len(response_a.json()) == 1
    assert len(response_b.json()) == 0


@pytest.mark.asyncio
async def test_get_ticket_by_owner_succeeds(client):
    token, _ = await _register(client)
    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {token}"},
    )
    ticket_id = purchase.json()["id"]

    response = await client.get(
        f"/api/tickets/{ticket_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["id"] == ticket_id


@pytest.mark.asyncio
async def test_get_ticket_by_non_owner_returns_404(client):
    token_a, _ = await _register(client, "Alice")
    token_b, _ = await _register(client, "Bob")

    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    ticket_id = purchase.json()["id"]

    response = await client.get(
        f"/api/tickets/{ticket_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_ticket_with_malformed_id_returns_422(client):
    token, _ = await _register(client)
    response = await client.get(
        "/api/tickets/not-a-uuid", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_nonexistent_ticket_returns_404(client):
    token, _ = await _register(client)
    response = await client.get(
        f"/api/tickets/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Revocation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_can_revoke_own_active_ticket(client):
    token, _ = await _register(client)
    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {token}"},
    )
    ticket_id = purchase.json()["id"]

    response = await client.post(
        f"/api/tickets/{ticket_id}/revoke", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_cannot_revoke_already_revoked_ticket(client):
    token, _ = await _register(client)
    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {token}"},
    )
    ticket_id = purchase.json()["id"]
    headers = {"Authorization": f"Bearer {token}"}

    await client.post(f"/api/tickets/{ticket_id}/revoke", headers=headers)
    second = await client.post(f"/api/tickets/{ticket_id}/revoke", headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_non_owner_cannot_revoke_ticket(client):
    token_a, _ = await _register(client, "Alice")
    token_b, _ = await _register(client, "Bob")

    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    ticket_id = purchase.json()["id"]

    response = await client.post(
        f"/api/tickets/{ticket_id}/revoke", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_requires_validator_role(client):
    token, _ = await _register(client)  # plain passenger
    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {token}"},
    )
    qr_payload = purchase.json()["qr_payload"]

    response = await client.post(
        "/api/tickets/validate",
        json={"qr_payload": qr_payload},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_validate_requires_authentication(client):
    response = await client.post("/api/tickets/validate", json={"qr_payload": "whatever"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_validator_can_validate_active_ticket(db_session, client):
    passenger_token, _ = await _register(client)
    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    qr_payload = purchase.json()["qr_payload"]

    validator_token = await _register_validator(db_session, client)
    response = await client.post(
        "/api/tickets/validate",
        json={"qr_payload": qr_payload},
        headers={"Authorization": f"Bearer {validator_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["ticket"]["status"] == "used"


@pytest.mark.asyncio
async def test_ticket_can_only_be_validated_once(db_session, client):
    passenger_token, _ = await _register(client)
    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    qr_payload = purchase.json()["qr_payload"]

    validator_token = await _register_validator(db_session, client)
    headers = {"Authorization": f"Bearer {validator_token}"}

    first = await client.post("/api/tickets/validate", json={"qr_payload": qr_payload}, headers=headers)
    assert first.json()["valid"] is True

    second = await client.post("/api/tickets/validate", json={"qr_payload": qr_payload}, headers=headers)
    assert second.status_code == 200
    body = second.json()
    assert body["valid"] is False
    assert "already been used" in body["reason"]


@pytest.mark.asyncio
async def test_revoked_ticket_fails_validation(db_session, client):
    passenger_token, _ = await _register(client)
    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    ticket_id = purchase.json()["id"]
    qr_payload = purchase.json()["qr_payload"]

    await client.post(
        f"/api/tickets/{ticket_id}/revoke",
        headers={"Authorization": f"Bearer {passenger_token}"},
    )

    validator_token = await _register_validator(db_session, client)
    response = await client.post(
        "/api/tickets/validate",
        json={"qr_payload": qr_payload},
        headers={"Authorization": f"Bearer {validator_token}"},
    )
    body = response.json()
    assert body["valid"] is False
    assert "revoked" in body["reason"]


@pytest.mark.asyncio
async def test_expired_ticket_fails_validation(db_session, client):
    passenger_token, passenger = await _register(client)
    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    ticket_id = purchase.json()["id"]

    # Force this ticket's valid_until into the past, directly in the DB -
    # expiry is enforced lazily (see ticketing/tickets/service.py), so
    # this simulates "time has passed" without needing to actually wait.
    ticket = await db_session.get(Ticket, uuid.UUID(ticket_id))
    ticket.valid_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    qr_payload = build_qr_payload(ticket_id=ticket.id, user_id=ticket.user_id)

    validator_token = await _register_validator(db_session, client)
    response = await client.post(
        "/api/tickets/validate",
        json={"qr_payload": qr_payload},
        headers={"Authorization": f"Bearer {validator_token}"},
    )
    body = response.json()
    assert body["valid"] is False
    assert "expired" in body["reason"]


@pytest.mark.asyncio
async def test_validate_rejects_malformed_qr_payload(db_session, client):
    validator_token = await _register_validator(db_session, client)
    response = await client.post(
        "/api/tickets/validate",
        json={"qr_payload": "not-a-real-payload"},
        headers={"Authorization": f"Bearer {validator_token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_validate_rejects_forged_qr_payload_for_nonexistent_ticket(db_session, client):
    validator_token = await _register_validator(db_session, client)
    forged_payload = build_qr_payload(ticket_id=uuid.uuid4(), user_id=uuid.uuid4())

    response = await client.post(
        "/api/tickets/validate",
        json={"qr_payload": forged_payload},
        headers={"Authorization": f"Bearer {validator_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["reason"] == "ticket not found"


@pytest.mark.asyncio
async def test_validate_rejects_qr_payload_with_mismatched_owner(db_session, client):
    passenger_token, _ = await _register(client)
    purchase = await client.post(
        "/api/tickets",
        json={"journey": _journey_payload()},
        headers={"Authorization": f"Bearer {passenger_token}"},
    )
    ticket_id = uuid.UUID(purchase.json()["id"])

    # A forged payload: real ticket id, but a different (also real, but
    # unrelated) user id as the claimed owner.
    forged_payload = build_qr_payload(ticket_id=ticket_id, user_id=uuid.uuid4())

    validator_token = await _register_validator(db_session, client)
    response = await client.post(
        "/api/tickets/validate",
        json={"qr_payload": forged_payload},
        headers={"Authorization": f"Bearer {validator_token}"},
    )
    body = response.json()
    assert body["valid"] is False
    assert body["reason"] == "ticket owner mismatch"
