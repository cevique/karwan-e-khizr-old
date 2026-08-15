"""
User-profile API: `/api/users/me`.

Deliberately thin - registration/login/current-user-via-token live under
`/api/auth` (see api/auth/router.py); this router exists so a client also
has a `/api/users/...`-namespaced way to read its own profile, per this
workstream's API layout instructions. It reuses the exact same
dependency/service calls as `GET /api/auth/me`, not a second
implementation.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from db.models.user import User
from users.dependencies import get_current_active_user
from users.schemas import UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def get_my_profile(user: User = Depends(get_current_active_user)) -> UserRead:
    return UserRead.model_validate(user)
