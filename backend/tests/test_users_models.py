"""
Tests for db/models/user.py.

Two tiers, matching the convention in tests/test_transit_models.py:

1. Metadata-only - no database required, always run.
2. Live-database - a real AsyncSession against DATABASE_URL, nested in a
   transaction that's always rolled back. Skipped if unreachable.
"""

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest
from sqlalchemy.exc import IntegrityError

from db.models.user import ROLE_PASSENGER, User
from tests._ticketing_test_support import database_reachable, db_session  # noqa: F401
from users.security import hash_password


# ---------------------------------------------------------------------------
# Metadata-only
# ---------------------------------------------------------------------------


def test_user_table_name():
    assert User.__tablename__ == "users"


def test_user_columns_present():
    columns = {c.name for c in User.__table__.columns}
    assert columns == {
        "id",
        "name",
        "email",
        "password_hash",
        "role",
        "is_active",
        "created_at",
        "updated_at",
    }


def test_user_email_column_is_unique():
    email_col = User.__table__.columns["email"]
    assert email_col.unique is True
    assert email_col.nullable is False


def test_user_role_defaults_to_passenger():
    assert User.__table__.columns["role"].default.arg == ROLE_PASSENGER


def test_user_is_active_defaults_true():
    assert User.__table__.columns["is_active"].default.arg is True


# ---------------------------------------------------------------------------
# Live database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_persists_hashed_password_not_plaintext(db_session):
    user = User(
        name="Ada Lovelace",
        email=f"ada-{uuid.uuid4()}@example.com",
        password_hash=hash_password("s3cret-password"),
    )
    db_session.add(user)
    await db_session.flush()

    assert user.id is not None
    assert user.password_hash != "s3cret-password"
    assert user.role == ROLE_PASSENGER
    assert user.is_active is True


@pytest.mark.asyncio
async def test_duplicate_email_violates_unique_constraint(db_session):
    email = f"dup-{uuid.uuid4()}@example.com"
    db_session.add(User(name="First", email=email, password_hash=hash_password("pw")))
    await db_session.flush()

    db_session.add(User(name="Second", email=email, password_hash=hash_password("pw")))
    with pytest.raises(IntegrityError):
        await db_session.flush()
