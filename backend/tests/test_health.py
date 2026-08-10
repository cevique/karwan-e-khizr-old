"""
Tests for GET /health.

The success-path tests exercise a real (SQLite-backed, in-memory) async
SQLAlchemy session, so `check_database()` genuinely executes `SELECT 1`
through SQLAlchemy - without requiring a running PostgreSQL/PostGIS
container or touching the real development database.

The failure-path tests override the session dependency with a stub whose
`execute()` raises, simulating an unreachable database, per the instruction
to prefer dependency overriding over deliberately shutting down the
developer's Postgres container.
"""

import os

# Settings requires DATABASE_URL/SECRET_KEY to be set; these values are only
# used to satisfy Settings validation for importing `main`/`db.session` in
# this test process - no test here actually connects using DATABASE_URL.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from db.session import get_session
from main import app


@pytest_asyncio.fixture
async def sqlite_session():
    """A real, isolated in-memory SQLite async session, used only to give
    the database check an actual database to execute `SELECT 1` against."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


class _BrokenSession:
    """Stub session whose `execute()` always raises, simulating an
    unreachable database without touching real infrastructure."""

    async def execute(self, *args, **kwargs):
        raise ConnectionRefusedError("simulated database outage")


async def _get(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_health_returns_200_and_ok_when_database_reachable(sqlite_session):
    async def override_get_session():
        yield sqlite_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        response = await _get("/health")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["api"]["status"] == "ok"
    assert body["database"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_response_has_expected_structure(sqlite_session):
    async def override_get_session():
        yield sqlite_session

    app.dependency_overrides[get_session] = override_get_session
    try:
        response = await _get("/health")
    finally:
        app.dependency_overrides.pop(get_session, None)

    body = response.json()
    assert set(body.keys()) == {"status", "api", "database"}
    assert set(body["api"].keys()) == {"status"}
    assert set(body["database"].keys()) == {"status"}
    # Nothing sensitive should ever appear in the response.
    serialized = response.text.lower()
    assert "database_url" not in serialized
    assert "secret_key" not in serialized
    assert "traceback" not in serialized


@pytest.mark.asyncio
async def test_database_check_actually_executes_a_query(sqlite_session):
    """Directly verifies the database check performs a real query execution
    (not a short-circuited/skipped check) against a real async session."""
    from api.health import check_database

    result = await check_database(sqlite_session)
    assert result.status == "ok"


@pytest.mark.asyncio
async def test_health_returns_503_when_database_unreachable():
    async def override_get_session():
        yield _BrokenSession()

    app.dependency_overrides[get_session] = override_get_session
    try:
        response = await _get("/health")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["api"]["status"] == "ok"
    assert body["database"]["status"] == "error"


@pytest.mark.asyncio
async def test_health_failure_does_not_crash_the_app():
    """The process must stay up after a failed DB check - verified by
    issuing a second, unrelated request immediately afterward."""

    async def override_get_session():
        yield _BrokenSession()

    app.dependency_overrides[get_session] = override_get_session
    try:
        failed = await _get("/health")
        assert failed.status_code == 503

        still_alive = await _get("/")
        assert still_alive.status_code == 200
    finally:
        app.dependency_overrides.pop(get_session, None)
