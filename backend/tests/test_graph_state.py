"""
Tests for `api.graph_state` (routing graph startup/rebuild/access) and
`main.py`'s lifespan wiring.

Unlike the rest of the routing test suite (which seeds data inside a
rolled-back transaction on one shared session), `build_and_store_graph`
deliberately opens its OWN, separate connection each time it's called
(via the shared `db.session.AsyncSessionLocal`, per this step's explicit
requirement not to introduce a second engine/session factory) - so seed
data must be genuinely committed to actually be visible to it, exactly as
it would be in production. Fixtures here commit their seed data for real
and clean it up explicitly afterward instead of relying on a rollback.

Several tests also drive the FastAPI app's *real* ASGI lifespan protocol
(`app.router.lifespan_context`) - the same code path uvicorn itself uses -
against the real database, rather than only calling
`build_and_store_graph` directly, so the startup wiring itself is
genuinely exercised, not just the function it calls.
"""

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import create_async_engine

from api.graph_state import build_and_store_graph, get_transit_graph
from core.config import settings
from db.models import Agency, Route, RouteStop, Stop
from routing.graph import TransitGraph


@pytest_asyncio.fixture(autouse=True)
async def _reset_shared_engine_pool():
    """`db.session.engine` is a process-wide singleton whose connection
    pool binds to whichever asyncio event loop first uses it.
    `build_and_store_graph` deliberately reuses this shared engine (this
    step's explicit requirement: no second engine/session factory), but
    pytest-asyncio gives each test function its own fresh event loop by
    default - so a pool already bound to an earlier test's loop breaks
    here with a low-level asyncpg error. Disposing it before every test
    forces a clean pool bound to the CURRENT test's loop on next use; this
    has no effect on real production behavior, where the process only
    ever has one event loop for its whole lifetime.
    """
    from db.session import engine

    await engine.dispose()
    yield


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
async def _require_database():
    """Skip (not fail) tests needing the real database when it's
    unreachable, matching the rest of the project's test convention -
    without the rolled-back-transaction session those other fixtures use,
    since this file's fixtures commit for real instead (see module
    docstring)."""
    if not await _database_reachable(settings.DATABASE_URL):
        pytest.skip(
            f"DATABASE_URL ({settings.DATABASE_URL}) is not reachable - "
            "skipping tests that need the real PostgreSQL/PostGIS database"
        )


@pytest_asyncio.fixture
async def seeded_network(_require_database):
    """One agency, one route, two stops connected by a ride edge -
    genuinely committed (not rolled back - see module docstring), so
    `build_and_store_graph`'s own, separate connection actually sees it.
    Cleaned up explicitly in a `finally` block afterward instead."""
    from db.session import AsyncSessionLocal

    agency_id = None
    s1 = s2 = None

    async with AsyncSessionLocal() as session:
        agency = Agency(name=f"Graph State Test Agency {uuid.uuid4()}")
        session.add(agency)
        await session.flush()

        route = Route(agency_id=agency.id, short_name="GS-1")
        session.add(route)
        await session.flush()

        s1 = Stop(name="GS Stop 1", location="SRID=4326;POINT(73.0479 33.6844)")
        s2 = Stop(name="GS Stop 2", location="SRID=4326;POINT(73.0490 33.6850)")
        session.add_all([s1, s2])
        await session.flush()

        session.add(RouteStop(route_id=route.id, stop_id=s1.id, sequence=1))
        session.add(RouteStop(route_id=route.id, stop_id=s2.id, sequence=2))
        await session.commit()

        agency_id = agency.id

    try:
        yield {"agency": agency, "route": route, "s1": s1, "s2": s2}
    finally:
        async with AsyncSessionLocal() as session:
            # Deleting the Agency cascades to Route and RouteStop (see the
            # FK ON DELETE CASCADE constraints), but Stops are agency-
            # independent and must be deleted explicitly.
            await session.execute(sa.delete(Agency).where(Agency.id == agency_id))
            await session.execute(
                sa.delete(Stop).where(Stop.id.in_([s1.id, s2.id]))
            )
            await session.commit()


def _make_test_app() -> FastAPI:
    """A bare FastAPI app - not `main.app` - so tests don't depend on or
    interfere with the real app's routers/health checks; only the graph
    lifecycle wiring itself is under test here."""
    return FastAPI()


# ---------------------------------------------------------------------------
# Startup builds and stores a graph; stored object is the expected TransitGraph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_and_store_graph_stores_a_transit_graph_on_app_state(
    seeded_network,
):
    app = _make_test_app()
    assert not hasattr(app.state, "transit_graph")

    result = await build_and_store_graph(app)

    assert isinstance(result, TransitGraph)
    assert app.state.transit_graph is result


@pytest.mark.asyncio
async def test_stored_graph_reflects_real_seeded_data(seeded_network):
    app = _make_test_app()
    graph = await build_and_store_graph(app)

    s1, s2 = seeded_network["s1"], seeded_network["s2"]
    assert s1.id in graph.nodes
    assert s2.id in graph.nodes
    ride_edge = next(
        e for e in graph.ride_edges if e.from_stop_id == s1.id and e.to_stop_id == s2.id
    )
    assert ride_edge.route_id == seeded_network["route"].id


@pytest.mark.asyncio
async def test_real_lifespan_protocol_builds_and_stores_the_graph(seeded_network):
    """Drives the actual ASGI lifespan context manager - the same code
    path uvicorn uses for startup/shutdown - against `main.py`'s real
    `lifespan` function, proving the wiring itself works end-to-end, not
    just `build_and_store_graph` in isolation."""
    import main as main_module

    app = main_module.app
    if hasattr(app.state, "transit_graph"):
        del app.state.transit_graph  # isolate from any prior test in this session

    async with app.router.lifespan_context(app):
        graph = app.state.transit_graph
        assert isinstance(graph, TransitGraph)
        assert seeded_network["s1"].id in graph.nodes
        assert seeded_network["s2"].id in graph.nodes


# ---------------------------------------------------------------------------
# Access via the dependency mechanism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_transit_graph_returns_the_stored_graph(seeded_network):
    app = _make_test_app()
    built_graph = await build_and_store_graph(app)

    fake_request = Request(scope={"type": "http", "app": app})
    resolved = get_transit_graph(fake_request)

    assert resolved is built_graph


def test_get_transit_graph_raises_if_called_before_any_build():
    app = _make_test_app()
    fake_request = Request(scope={"type": "http", "app": app})

    with pytest.raises(AttributeError):
        get_transit_graph(fake_request)


@pytest.mark.asyncio
async def test_get_transit_graph_works_through_a_real_endpoint(seeded_network):
    """End-to-end: a route handler using `Depends(get_transit_graph)`
    genuinely receives the graph built at startup, via a real HTTP
    request through the ASGI stack (not just direct function calls)."""
    from fastapi import Depends
    from httpx import ASGITransport, AsyncClient

    app = _make_test_app()
    await build_and_store_graph(app)

    @app.get("/_test/node-count")
    async def node_count(graph: TransitGraph = Depends(get_transit_graph)) -> dict:
        return {"node_count": len(graph.nodes)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/_test/node-count")

    assert response.status_code == 200
    assert response.json()["node_count"] == len(app.state.transit_graph.nodes)


# ---------------------------------------------------------------------------
# Rebuild: new graph, old reference untouched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rebuild_replaces_the_stored_graph_with_a_new_object(seeded_network):
    app = _make_test_app()
    first_graph = await build_and_store_graph(app)
    second_graph = await build_and_store_graph(app)

    assert second_graph is not first_graph
    assert app.state.transit_graph is second_graph


@pytest.mark.asyncio
async def test_old_graph_reference_remains_valid_and_unchanged_after_rebuild(
    seeded_network,
):
    """Simulates an in-flight request holding a reference to the graph
    from before a rebuild: that reference must still work correctly and
    must not reflect whatever the rebuild produced (they happen to be
    content-equal here since nothing changed in the DB between builds,
    but the object identity and read-only guarantees must hold)."""
    app = _make_test_app()
    in_flight_request_graph = await build_and_store_graph(app)

    captured_nodes = in_flight_request_graph.nodes
    captured_ride_edges = in_flight_request_graph.ride_edges
    captured_node_count = len(in_flight_request_graph.nodes)

    # Simulate a concurrent rebuild happening while that "request" is
    # still holding its own reference.
    await build_and_store_graph(app)

    # The old object itself is completely untouched.
    assert in_flight_request_graph.nodes is captured_nodes
    assert in_flight_request_graph.ride_edges is captured_ride_edges
    assert len(in_flight_request_graph.nodes) == captured_node_count

    # And it's still genuinely usable/read-only, exactly as before.
    with pytest.raises(TypeError):
        in_flight_request_graph.nodes[uuid.uuid4()] = None
    with pytest.raises(AttributeError):
        in_flight_request_graph.ride_edges.append(None)

    # app.state has moved on to the new graph, not the old one.
    assert app.state.transit_graph is not in_flight_request_graph


@pytest.mark.asyncio
async def test_rebuild_reflects_data_added_between_builds(_require_database):
    """A more direct proof a rebuild actually re-reads the database:
    build once, add a stop (committed for real - see module docstring),
    rebuild, confirm the new stop appears only in the second graph."""
    from db.session import AsyncSessionLocal

    app = _make_test_app()
    first_graph = await build_and_store_graph(app)
    first_node_count = len(first_graph.nodes)

    new_stop = Stop(name="Newly Added Stop", location="SRID=4326;POINT(73.05 33.70)")
    async with AsyncSessionLocal() as session:
        session.add(new_stop)
        await session.commit()

    try:
        second_graph = await build_and_store_graph(app)

        assert new_stop.id not in first_graph.nodes
        assert new_stop.id in second_graph.nodes
        assert len(second_graph.nodes) == first_node_count + 1
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(sa.delete(Stop).where(Stop.id == new_stop.id))
            await session.commit()


# ---------------------------------------------------------------------------
# Startup failure propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_and_store_graph_propagates_database_errors():
    """A session bound to a nonexistent database must cause
    build_and_store_graph to raise, not silently store an empty/partial
    graph."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import api.graph_state as graph_state_module

    broken_engine = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/this_database_does_not_exist"
    )
    broken_session_factory = async_sessionmaker(
        bind=broken_engine, expire_on_commit=False
    )

    app = _make_test_app()
    original_factory = graph_state_module.AsyncSessionLocal
    graph_state_module.AsyncSessionLocal = broken_session_factory
    try:
        with pytest.raises(Exception):  # noqa: B017 - genuinely any DB error is fine here
            await build_and_store_graph(app)
    finally:
        graph_state_module.AsyncSessionLocal = original_factory
        await broken_engine.dispose()

    assert not hasattr(app.state, "transit_graph")


@pytest.mark.asyncio
async def test_lifespan_startup_failure_propagates_and_leaves_state_unset():
    """Drives the real lifespan protocol with a broken DB connection,
    confirming FastAPI/Starlette's own lifespan machinery sees the
    exception rather than it being swallowed anywhere in this project's
    code - this is what makes `uvicorn` itself refuse to start serving."""
    from contextlib import asynccontextmanager

    from sqlalchemy.ext.asyncio import async_sessionmaker

    import api.graph_state as graph_state_module

    broken_engine = create_async_engine(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/this_database_does_not_exist"
    )
    broken_session_factory = async_sessionmaker(
        bind=broken_engine, expire_on_commit=False
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await build_and_store_graph(app)
        yield

    app = FastAPI(lifespan=lifespan)

    original_factory = graph_state_module.AsyncSessionLocal
    graph_state_module.AsyncSessionLocal = broken_session_factory
    try:
        with pytest.raises(Exception):  # noqa: B017
            async with app.router.lifespan_context(app):
                pytest.fail("should never reach inside the context manager")
    finally:
        graph_state_module.AsyncSessionLocal = original_factory
        await broken_engine.dispose()

    assert not hasattr(app.state, "transit_graph")
