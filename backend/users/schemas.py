"""
Pydantic schemas for users/authentication. Never a raw ORM `User` object
is returned from any endpoint - `UserRead` deliberately has no
`password_hash` field.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Request body for `POST /api/auth/register`.

    Self-registration always produces a `role="passenger"` account - see
    `users/service.py::register_user`. There is no way to register as
    "validator"/"admin" through this endpoint.
    """

    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class UserLoginRequest(BaseModel):
    """Request body for `POST /api/auth/login`."""

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserRead(BaseModel):
    """Public representation of a User - no password hash, ever."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Response body for `POST /api/auth/register` and `POST
    /api/auth/login` - a bearer access token plus the user it belongs to,
    so a client doesn't need a second round trip to `GET /api/auth/me`
    right after registering/logging in."""

    access_token: str
    token_type: str = "bearer"
    user: UserRead
