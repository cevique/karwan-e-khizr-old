"""
Shared test support for this workstream's tests
(test_users_*.py / test_auth_*.py / test_fares_*.py / test_ticketing_*.py).

Not a test module itself (no `test_` prefix - pytest won't collect it).

Deliberately does NOT import `main.app` (built by `main.py`, which wires
up the routing-graph startup lifecycle this workstream doesn't need and
must not depend on). Instead, `build_app()` constructs its own minimal
`FastAPI` app with only this workstream's routers mounted - independent
of `api/router.py`/`main.py`, matching how they'll actually be registered
later (see the top-level instructions' "API" section: "Create router
objects that I can register later").

Reuses the exact same real-database, rolled-back-transaction pattern as
`tests/test_transit_api.py`'s `db_session`/`client` fixtures (a real
`AsyncSession` nested in a transaction that's always rolled back, and an
`httpx.ASGITransport` client wired to it via a `get_session` override) -
copied here rather than imported, since modifying that existing test file
is out of scope for this workstream.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from api.auth.router import router as auth_router
from api.fares.router import router as fares_router
from api.tickets.router import router as tickets_router
from api.users.router import router as users_router
from core.config import settings
from db.session import get_session


async def database_reachable(url: str) -> bool:
    try:
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


def build_app() -> FastAPI:
    """A minimal FastAPI app with only this workstream's routers mounted
    under `/api`, matching their real eventual mount points."""
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    app.include_router(users_router, prefix="/api")
    app.include_router(fares_router, prefix="/api")
    app.include_router(tickets_router, prefix="/api")
    return app


@pytest_asyncio.fixture
async def db_session():
    """Same pattern as tests/test_transit_api.py's fixture of the same
    name: a real AsyncSession, nested in a transaction that's always
    rolled back on teardown, so nothing committed here persists."""
    if not await database_reachable(settings.DATABASE_URL):
        import pytest

        pytest.skip(
            f"DATABASE_URL ({settings.DATABASE_URL}) is not reachable - "
            "skipping tests that need the real PostgreSQL database"
        )

    engine = create_async_engine(settings.DATABASE_URL)
    connection = await engine.connect()
    outer_transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)

    await connection.begin_nested()

    @sa.event.listens_for(session.sync_session, "after_transaction_end")
    def _restart_savepoint(sync_session, transaction):
        if transaction.nested and not transaction._parent.nested:
            sync_session.begin_nested()

    try:
        yield session
    finally:
        await session.close()
        await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    """An httpx AsyncClient wired to a fresh `build_app()` instance, with
    `get_session` overridden to yield the rolled-back `db_session`."""
    app = build_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
