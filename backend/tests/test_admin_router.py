"""
Tests for `api.admin.router` and `api.dev.router` - HTTP-level tests
against a dedicated, bare FastAPI app (NOT `main.app`, which this
workstream is forbidden from modifying / these routers are deliberately
not registered on - see both routers' module docstrings) with these two
routers mounted directly, mirroring `tests/test_graph_state.py`'s
`_make_test_app()` pattern for exactly the same reason: keep this app
independent of, and non-mutating toward, the real application object.

Most endpoints here have `get_session` overridden to the same rolled-
back-on-teardown SAVEPOINT session used throughout this project's test
suite, so nothing they write persists. The one exception is
`/admin/graph/rebuild`: it calls the existing `api.graph_state.
build_and_store_graph`, which deliberately opens its OWN, separate
connection (see that module and `test_graph_state.py`'s docstrings) - so
seeing it reflect seeded data requires genuinely COMMITTED data, cleaned
up explicitly afterward instead of relying on rollback (same approach
`test_graph_state.py` uses for its own `seeded_network` fixture).
"""

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from api.admin.router import router as admin_router  # noqa: E402
from api.dev.router import router as dev_router  # noqa: E402
from core.config import settings  # noqa: E402
from data.seed_dataset import SEED_AGENCIES, SEED_STOPS  # noqa: E402
from db.session import get_session  # noqa: E402
from seeding.seed import clear_seed_data, seed_database  # noqa: E402


async def _database_reachable(url: str) -> bool:
    try:
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def db_session():
    """Same rolled-back SAVEPOINT session pattern used throughout this
    project's test suite (see e.g. tests/test_transit_models.py)."""
    if not await _database_reachable(settings.DATABASE_URL):
        pytest.skip(
            f"DATABASE_URL ({settings.DATABASE_URL}) is not reachable - "
            "skipping tests that need the real PostgreSQL/PostGIS database"
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


def _make_test_app(session: AsyncSession) -> FastAPI:
    """A bare FastAPI app with only the admin/dev routers mounted, and
    `get_session` overridden to the given (rolled-back-on-teardown)
    session - never `main.app`, which this workstream doesn't modify and
    doesn't register these routers on."""
    app = FastAPI()
    app.include_router(admin_router, prefix="/api")
    app.include_router(dev_router, prefix="/api")

    async def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    return app


@pytest_asyncio.fixture
async def client(db_session):
    app = _make_test_app(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# /admin/seed, /admin/seed/reset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_endpoint_creates_dataset(client):
    response = await client.post("/api/admin/seed")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "insert"
    assert body["agencies_created"] == len(SEED_AGENCIES)
    assert body["stops_created"] == len(SEED_STOPS)


@pytest.mark.asyncio
async def test_seed_endpoint_is_repeatable(client):
    first = await client.post("/api/admin/seed")
    assert first.json()["agencies_created"] == len(SEED_AGENCIES)

    second = await client.post("/api/admin/seed")
    assert second.json()["agencies_created"] == 0
    assert second.json()["agencies_skipped"] == len(SEED_AGENCIES)


@pytest.mark.asyncio
async def test_seed_endpoint_rejects_unknown_mode(client):
    response = await client.post("/api/admin/seed", json={"mode": "bogus"})
    assert response.status_code == 422  # pydantic Literal validation


@pytest.mark.asyncio
async def test_seed_reset_endpoint(client):
    await client.post("/api/admin/seed")
    response = await client.post("/api/admin/seed/reset")
    assert response.status_code == 200

    status_response = await client.get("/api/dev/status")
    assert status_response.json()["seed_agencies_present"] == 0


# ---------------------------------------------------------------------------
# /admin/import, /admin/import/csv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_endpoint_success(client):
    agency_name = f"API Import Agency {uuid.uuid4()}"
    payload = {
        "agencies": [{"name": agency_name}],
        "stops": [
            {"ref": "s1", "name": "API Stop 1", "latitude": 33.7, "longitude": 73.05},
            {"ref": "s2", "name": "API Stop 2", "latitude": 33.71, "longitude": 73.06},
        ],
        "routes": [{"ref": "r1", "agency": agency_name, "short_name": "AI-1"}],
        "route_stops": [
            {"route_ref": "r1", "stop_ref": "s1", "sequence": 1},
            {"route_ref": "r1", "stop_ref": "s2", "sequence": 2},
        ],
    }
    response = await client.post("/api/admin/import", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["agencies_created"] == 1
    assert body["stops_created"] == 2
    assert body["routes_created"] == 1
    assert body["route_stops_created"] == 2


@pytest.mark.asyncio
async def test_import_endpoint_rejects_invalid_dataset(client):
    payload = {
        "agencies": [{"name": "Bad Import Agency"}],
        "stops": [
            {"ref": "s1", "name": "Only Stop", "latitude": 33.7, "longitude": 73.0}
        ],
        "routes": [{"ref": "r1", "agency": "Bad Import Agency", "short_name": "BAD-1"}],
        "route_stops": [{"route_ref": "r1", "stop_ref": "s1", "sequence": 1}],
    }
    response = await client.post("/api/admin/import", json=payload)
    assert response.status_code == 422
    errors = response.json()["detail"]["errors"]
    assert any(e["code"] == "insufficient_stops" for e in errors)


@pytest.mark.asyncio
async def test_import_csv_endpoint_success(client):
    files = {
        "agencies": ("agencies.csv", "name,network_type\nCSV Agency,brt\n"),
        "stops": (
            "stops.csv",
            "ref,name,latitude,longitude\n"
            "s1,CSV Stop 1,33.7,73.05\n"
            "s2,CSV Stop 2,33.71,73.06\n",
        ),
        "routes": ("routes.csv", "ref,agency,short_name\nr1,CSV Agency,CS-1\n"),
        "route_stops": (
            "route_stops.csv",
            "route_ref,stop_ref,sequence\nr1,s1,1\nr1,s2,2\n",
        ),
    }
    response = await client.post(
        "/api/admin/import/csv",
        files={k: (v[0], v[1], "text/csv") for k, v in files.items()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["agencies_created"] == 1
    assert body["route_stops_created"] == 2


@pytest.mark.asyncio
async def test_import_csv_endpoint_rejects_malformed_csv(client):
    response = await client.post(
        "/api/admin/import/csv",
        files={
            "stops": (
                "stops.csv",
                "ref,name,latitude\ns1,Missing Longitude Column,33.7\n",
                "text/csv",
            )
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /dev/status, /dev/validate, /dev/validate/seed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_endpoint_reflects_seeded_data(client):
    before = await client.get("/api/dev/status")
    assert before.json()["seed_agencies_present"] == 0

    await client.post("/api/admin/seed")

    after = await client.get("/api/dev/status")
    body = after.json()
    assert body["seed_agencies_present"] == len(SEED_AGENCIES)
    assert body["agencies_total"] >= len(SEED_AGENCIES)
    assert body["transit_graph_loaded"] is False


@pytest.mark.asyncio
async def test_validate_endpoint_reports_errors_without_persisting(client):
    payload = {
        "agencies": [],
        "stops": [{"ref": "s1", "name": "Bad Coords", "latitude": 999, "longitude": 1}],
        "routes": [],
        "route_stops": [],
    }
    response = await client.post("/api/dev/validate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is False
    assert any(e["code"] == "invalid_coordinates" for e in body["errors"])

    status_response = await client.get("/api/dev/status")
    assert status_response.json()["stops_total"] == 0


@pytest.mark.asyncio
async def test_validate_seed_endpoint_reports_the_seed_dataset_is_valid(client):
    response = await client.post("/api/dev/validate/seed")
    assert response.status_code == 200
    assert response.json()["is_valid"] is True


# ---------------------------------------------------------------------------
# /admin/graph/rebuild - needs genuinely committed data (own connection)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _reset_shared_engine_pool():
    """Copied from tests/test_graph_state.py: `db.session.engine` is a
    process-wide singleton bound to whichever event loop first used it;
    disposing it before this fixture's test forces a clean pool bound to
    the CURRENT test's loop. See that file's docstring for the full
    explanation - required here for the same reason (this test drives
    `build_and_store_graph`, which reuses that shared engine)."""
    from db.session import engine

    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def committed_seed(_reset_shared_engine_pool):
    """Genuinely commits the seed dataset (not the rolled-back
    `db_session` fixture) so `build_and_store_graph`'s own, separate
    connection actually sees it - then cleans up explicitly afterward,
    mirroring `test_graph_state.py`'s `seeded_network` fixture."""
    if not await _database_reachable(settings.DATABASE_URL):
        pytest.skip(
            f"DATABASE_URL ({settings.DATABASE_URL}) is not reachable - "
            "skipping tests that need the real PostgreSQL/PostGIS database"
        )

    from db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await seed_database(session, mode="insert")

    try:
        yield
    finally:
        async with AsyncSessionLocal() as session:
            await clear_seed_data(session)


@pytest.mark.asyncio
async def test_graph_rebuild_endpoint_reflects_committed_seed_data(committed_seed):
    app = FastAPI()
    app.include_router(admin_router, prefix="/api")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/admin/graph/rebuild")

    assert response.status_code == 200
    body = response.json()
    assert body["node_count"] >= len(SEED_STOPS)
    assert body["ride_edge_count"] > 0
    assert app.state.transit_graph is not None
