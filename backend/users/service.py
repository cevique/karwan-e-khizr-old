"""
User business logic: registration, authentication, and lookups.

Kept as plain async functions taking an `AsyncSession` (matching the
style of `db/session.py::get_session` and the rest of this codebase's
service-ish helpers) rather than a class - a hackathon-appropriate amount
of structure.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.user import ROLE_PASSENGER, User
from users.security import hash_password, verify_password


class EmailAlreadyRegisteredError(Exception):
    """Raised by `register_user` when the (normalized) email is already
    taken."""


def _normalize_email(email: str) -> str:
    """Lowercase + strip whitespace, so "Foo@Bar.com " and "foo@bar.com"
    are treated as the same login identifier both at registration and at
    login time."""
    return email.strip().lower()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    normalized = _normalize_email(email)
    result = await session.execute(select(User).where(User.email == normalized))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def register_user(session: AsyncSession, name: str, email: str, password: str) -> User:
    """Create a new `role="passenger"` account.

    Raises `EmailAlreadyRegisteredError` if the normalized email is
    already in use. Does NOT commit - the caller (the API route) commits,
    so it stays in control of the transaction boundary.
    """
    normalized_email = _normalize_email(email)

    existing = await get_user_by_email(session, normalized_email)
    if existing is not None:
        raise EmailAlreadyRegisteredError(normalized_email)

    user = User(
        name=name.strip(),
        email=normalized_email,
        password_hash=hash_password(password),
        role=ROLE_PASSENGER,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    """Return the `User` if `email`/`password` are a valid, active
    account's credentials, else `None`.

    Deliberately does the same amount of work (a password hash
    comparison) whether or not the account exists, using a fixed dummy
    hash for the "no such user" case - a small mitigation against
    timing-based user enumeration.
    """
    user = await get_user_by_email(session, email)

    # A syntactically-valid bcrypt hash of an unguessable value, used only
    # so `verify_password` does real bcrypt work (and takes comparable
    # time) even when no such user exists.
    dummy_hash = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO7VDXlA6ZKMqQxT5Pe5x2j9j9j9j9j9u"

    if user is None:
        verify_password(password, dummy_hash)
        return None

    if not verify_password(password, user.password_hash):
        return None

    if not user.is_active:
        return None

    return user
