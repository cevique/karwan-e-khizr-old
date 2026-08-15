"""
Authentication API: register, login, current-user.

Mounted at `/api/auth` once registered by whoever owns `api/router.py`
(not this workstream - see this project's ownership boundaries; this
module only defines the `APIRouter` object).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.user import User
from db.session import get_session
from users.dependencies import get_current_active_user
from users.schemas import TokenResponse, UserLoginRequest, UserRead, UserRegisterRequest
from users.security import create_access_token
from users.service import EmailAlreadyRegisteredError, authenticate_user, register_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: UserRegisterRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    try:
        user = await register_user(session, name=body.name, email=body.email, password=body.password)
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email is already registered"
        ) from None

    await session.commit()
    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(
    body: UserLoginRequest, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    user = await authenticate_user(session, email=body.email, password=body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        )

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(get_current_active_user)) -> UserRead:
    return UserRead.model_validate(user)
