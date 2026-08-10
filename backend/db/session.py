"""
Asynchronous SQLAlchemy engine and session infrastructure.

This module creates a single async engine and session factory for the whole
application, bound to the `DATABASE_URL` from the existing Pydantic Settings
configuration (`core.config.settings`). It intentionally does not define any
FastAPI dependencies beyond the plain `get_session` async generator below,
which is framework-agnostic and can be wrapped with `Depends(get_session)`
once the API layer exists.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings

# Single async engine for the application process, using the asyncpg dialect
# via the DATABASE_URL configured in core/config.py / .env (never hardcoded
# here). `echo` mirrors DEBUG so SQL statements are only logged in
# development. No pool-size/overflow tuning is set here on purpose - the
# defaults are appropriate for now and premature tuning is out of scope for
# this step.
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
)

# Session factory bound to `engine`. `expire_on_commit=False` keeps ORM
# instances usable after a commit without an implicit re-fetch, which is the
# usual expectation for async request/response cycles (e.g., a future
# FastAPI request handler that returns a model right after committing it).
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an `AsyncSession` bound to the application engine.

    Framework-agnostic on purpose: it is a plain async generator so it can be
    used directly (`async with`/`async for`) or wrapped as a FastAPI
    dependency (`Depends(get_session)`) once the API layer is implemented.
    The session is always closed on exit, including when an exception is
    raised while it is in use.
    """
    async with AsyncSessionLocal() as session:
        yield session
