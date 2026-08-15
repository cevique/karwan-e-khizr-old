"""
Password hashing and JWT access-token helpers.

Password hashing uses bcrypt directly (not passlib) - bcrypt's own API is
already a two-function surface (`hashpw`/`checkpw`), so calling it
directly avoids an extra dependency layer for no real benefit.

JWT access tokens use PyJWT with HS256, signed with the application's own
`SECRET_KEY` (from `core.config.settings` - required, has no default, and
is loaded from the environment/.env there; nothing in this module ever
hardcodes or duplicates it). This is the same signing key used for QR
ticket payloads (see `ticketing.tickets.qr`) - both are HMAC-signed
application secrets, not independent trust roots, which is fine for a
single-backend hackathon deployment.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt.

    Returns a UTF-8 string (bcrypt's own encoded hash format, including
    its salt) suitable for storage in `User.password_hash`.
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash.

    Never raises on a malformed/foreign hash value - that's treated as a
    failed verification rather than a 500, since callers only care
    whether the password is correct, not why a check failed.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


class InvalidTokenError(Exception):
    """Raised for any structurally-invalid, expired, or wrong-type token."""


def create_access_token(user_id: uuid.UUID) -> str:
    """Issue a signed JWT access token for `user_id`.

    Expires after `settings.ACCESS_TOKEN_EXPIRE_MINUTES` (existing,
    already-configured setting - see core/config.py).
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """Verify and decode an access token, returning the embedded user id.

    Raises `InvalidTokenError` for any failure (expired, bad signature,
    malformed, wrong `type`) so callers don't need to know PyJWT's own
    exception hierarchy.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError("not an access token")

    sub = payload.get("sub")
    if not sub:
        raise InvalidTokenError("missing subject")

    try:
        return uuid.UUID(str(sub))
    except (ValueError, AttributeError, TypeError) as exc:
        raise InvalidTokenError("malformed subject") from exc
