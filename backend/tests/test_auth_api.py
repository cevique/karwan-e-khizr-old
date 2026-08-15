"""
Tests for the authentication API (api/auth/router.py, api/users/router.py).

Reuses the db_session/client fixtures from tests/_ticketing_test_support.py
(the same real-database, rolled-back-transaction pattern used elsewhere in
this codebase's API tests).
"""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import uuid

import pytest

from tests._ticketing_test_support import client, db_session  # noqa: F401


def _unique_email() -> str:
    return f"user-{uuid.uuid4()}@example.com"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_creates_user_and_returns_token(client):
    email = _unique_email()
    response = await client.post(
        "/api/auth/register",
        json={"name": "Ada Lovelace", "email": email, "password": "correct-horse-battery"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email.lower()
    assert body["user"]["role"] == "passenger"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(client):
    email = _unique_email()
    payload = {"name": "Ada", "email": email, "password": "correct-horse-battery"}

    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_register_duplicate_email_is_case_insensitive(client):
    email = _unique_email()
    await client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": email, "password": "correct-horse-battery"},
    )

    response = await client.post(
        "/api/auth/register",
        json={"name": "Ada2", "email": email.upper(), "password": "another-password"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_register_rejects_short_password(client):
    response = await client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": _unique_email(), "password": "short"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_invalid_email(client):
    response = await client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "not-an-email", "password": "correct-horse-battery"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_correct_credentials_succeeds(client):
    email = _unique_email()
    await client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": email, "password": "correct-horse-battery"},
    )

    response = await client.post(
        "/api/auth/login", json={"email": email, "password": "correct-horse-battery"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["user"]["email"] == email.lower()


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(client):
    email = _unique_email()
    await client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": email, "password": "correct-horse-battery"},
    )

    response = await client.post(
        "/api/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_with_nonexistent_email_returns_401(client):
    response = await client.post(
        "/api/auth/login",
        json={"email": _unique_email(), "password": "whatever-password"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Current user / protected endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_requires_authentication(client):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_rejects_malformed_token(client):
    response = await client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_current_user_with_valid_token(client):
    email = _unique_email()
    register_response = await client.post(
        "/api/auth/register",
        json={"name": "Ada Lovelace", "email": email, "password": "correct-horse-battery"},
    )
    token = register_response.json()["access_token"]

    response = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == email.lower()


@pytest.mark.asyncio
async def test_users_me_alias_matches_auth_me(client):
    email = _unique_email()
    register_response = await client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": email, "password": "correct-horse-battery"},
    )
    token = register_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    auth_me = await client.get("/api/auth/me", headers=headers)
    users_me = await client.get("/api/users/me", headers=headers)

    assert auth_me.status_code == users_me.status_code == 200
    assert auth_me.json() == users_me.json()
