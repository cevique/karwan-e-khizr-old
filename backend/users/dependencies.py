"""
FastAPI dependency functions for authentication/authorization.

`get_current_user` reads the `Authorization: Bearer <token>` header,
verifies it (`users/security.py`), and loads the corresponding `User` row
from the database - this is the single source of truth for "who is
making this request" that every other protected endpoint in this
workstream (`api/users`, `api/tickets`) depends on.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.user import User
from db.session import get_session
from users.security import InvalidTokenError, decode_access_token
from users.service import get_user_by_id

# `auto_error=False` so `get_optional_current_user` can distinguish "no
# credentials supplied" from "bad credentials supplied" itself, rather
# than FastAPI/Starlette raising a 403 before this module gets a chance
# to treat a missing header as "anonymous" instead of an error.
_bearer_scheme = HTTPBearer(auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Require a valid bearer token; resolve it to its `User` row.

    Raises 401 if the header is missing, the token is invalid/expired, or
    the token's subject no longer corresponds to a user (e.g. deleted).
    """
    if credentials is None or not credentials.credentials:
        raise _CREDENTIALS_ERROR

    try:
        user_id = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise _CREDENTIALS_ERROR from None

    user = await get_user_by_id(session, user_id)
    if user is None:
        raise _CREDENTIALS_ERROR

    return user


async def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    """Same as `get_current_user`, but also rejects deactivated
    accounts (403, not 401 - the credentials themselves were valid)."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user account"
        )
    return user


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Like `get_current_user`, but returns `None` instead of raising when
    no credentials are supplied at all. Still raises 401 for a *present
    but invalid* token - an endpoint that accepts anonymous callers
    should not silently ignore a caller's broken/expired token."""
    if credentials is None or not credentials.credentials:
        return None
    return await get_current_user(credentials=credentials, session=session)


def require_role(*roles: str):
    """Dependency factory: require the current active user to have one of
    `roles`. Used for the ticket-validation endpoint (validator/admin
    only) - see api/tickets/router.py."""

    async def _dependency(user: User = Depends(get_current_active_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return user

    return _dependency
