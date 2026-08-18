"""
Phase 5 tests (plan.md section M): `seeding.trip_generator` (pure-ish
logic, small DB-backed cases with a synthetic dataset) and
`POST /admin/trips/generate` (HTTP-level, including against the REAL
canonical `docs/transit_data.json` for the plan's own "generate FR-04,
verify count 97" acceptance check).

Mirrors `tests/test_admin_router.py`'s conventions throughout: a bare
FastAPI app with only `admin_router` mounted (never `main.app`, which
this workstream doesn't modify - see that router's module docstring),
and the same rolled-back SAVEPOINT `db_session` fixture used everywhere
else in this suite.
"""

from __future__ import annotations

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

from datetime import date  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from api.admin.router import router as admin_router  # noqa: E402
from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop, StopTime, Trip  # noqa: E402
from db.session import get_session  # noqa: E402
from seeding.import_schema import (  # noqa: E402
    ImportAgency,
    ImportDataset,
    ImportRoute,
    ImportRouteStop,
    ImportStop,
    ImportStopTime,
    ImportTripPattern,
)
from seeding.importer import ImportValidationError, import_dataset  # noqa: E402
from seeding.transit_data_importer import load_transit_data  # noqa: E402
from seeding.trip_generator import (  # noqa: E402
    DEFAULT_TRANSIT_DATA_PATH,
    NoCanonicalTripPattern,
    dataset_for_route,
    find_import_route,
    generate_daily_trips,
)


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
    """Same bare-app pattern as `tests/test_admin_router.py::_make_test_app`
    - never `main.app`."""
    app = FastAPI()
    app.include_router(admin_router, prefix="/api")

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
# Fixtures: a small synthetic canonical dataset with ONE route/pattern,
# and matching "already imported" DB rows for it - deliberately NOT the
# real transit_data.json, so most tests here are fast and independent of
# the real research dataset's specific numbers.
# ---------------------------------------------------------------------------


def _synthetic_dataset(agency_name: str, route_ref: str, route_short_name: str):
    stop_refs = (f"{route_ref}-s1", f"{route_ref}-s2")
    return ImportDataset(
        agencies=(ImportAgency(name=agency_name),),
        stops=tuple(ImportStop(ref=ref, name=ref) for ref in stop_refs),
        routes=(ImportRoute(ref=route_ref, agency=agency_name, short_name=route_short_name),),
        route_stops=(
            ImportRouteStop(route_ref=route_ref, stop_ref=stop_refs[0], sequence=1),
            ImportRouteStop(route_ref=route_ref, stop_ref=stop_refs[1], sequence=2),
        ),
        trip_patterns=(
            ImportTripPattern(
                route_ref=route_ref,
                direction="forward",
                headway_minutes=30,
                total_trips_per_day=3,
                first_trip_start="06:00:00",
                last_trip_start="07:00:00",
                source_pdf="synthetic-test-fixture",
                confidence="OFFICIAL",
            ),
        ),
        trip_stop_times={
            (route_ref, "forward"): (
                ImportStopTime(
                    stop_ref=stop_refs[0], sequence=1, arrival_offset_s=0, departure_offset_s=0
                ),
                ImportStopTime(
                    stop_ref=stop_refs[1],
                    sequence=2,
                    arrival_offset_s=300,
                    departure_offset_s=300,
                ),
            )
        },
    )


async def _make_already_imported_route(db_session, agency_name: str, route_short_name: str):
    """Create Agency/Route/Stop/RouteStop rows directly via the ORM - NOT
    through `import_dataset` - to mirror "this route was already
    imported at some point in the past" without depending on the import
    pipeline itself in every test."""
    route_ref = f"route-{uuid.uuid4().hex[:8]}"
    stop_refs = (f"{route_ref}-s1", f"{route_ref}-s2")

    agency = Agency(name=agency_name, network_type="brt")
    db_session.add(agency)
    await db_session.flush()

    route = Route(agency_id=agency.id, short_name=route_short_name, long_name="Synthetic Route")
    db_session.add(route)
    await db_session.flush()

    stop_a = Stop(ref=stop_refs[0], name="Synthetic Stop A")
    stop_b = Stop(ref=stop_refs[1], name="Synthetic Stop B")
    db_session.add_all([stop_a, stop_b])
    await db_session.flush()

    db_session.add_all(
        [
            RouteStop(route_id=route.id, stop_id=stop_a.id, sequence=1),
            RouteStop(route_id=route.id, stop_id=stop_b.id, sequence=2),
        ]
    )
    await db_session.flush()

    dataset = _synthetic_dataset(agency_name, route_ref, route_short_name)
    return route, dataset


# ---------------------------------------------------------------------------
# seeding.trip_generator: pure dataset-slicing logic
# ---------------------------------------------------------------------------


def test_find_import_route_matches_by_agency_and_short_name():
    dataset = _synthetic_dataset("Agency X", "r1", "R-1")
    route = Route(short_name="R-1")
    found = find_import_route(dataset, route, "Agency X")
    assert found is not None
    assert found.ref == "r1"


def test_find_import_route_returns_none_for_wrong_agency():
    dataset = _synthetic_dataset("Agency X", "r1", "R-1")
    route = Route(short_name="R-1")
    assert find_import_route(dataset, route, "A Different Agency") is None


def test_find_import_route_returns_none_when_short_name_not_in_dataset():
    dataset = _synthetic_dataset("Agency X", "r1", "R-1")
    route = Route(short_name="NOT-IN-DATASET")
    assert find_import_route(dataset, route, "Agency X") is None


def test_dataset_for_route_includes_only_that_routes_data():
    combined = ImportDataset(
        agencies=(ImportAgency(name="Agency A"), ImportAgency(name="Agency B")),
        stops=(
            ImportStop(ref="a-s1", name="A Stop 1"),
            ImportStop(ref="b-s1", name="B Stop 1"),
        ),
        routes=(
            ImportRoute(ref="route-a", agency="Agency A", short_name="A-1"),
            ImportRoute(ref="route-b", agency="Agency B", short_name="B-1"),
        ),
        route_stops=(
            ImportRouteStop(route_ref="route-a", stop_ref="a-s1", sequence=1),
            ImportRouteStop(route_ref="route-b", stop_ref="b-s1", sequence=1),
        ),
        trip_patterns=(
            ImportTripPattern(
                route_ref="route-a",
                direction="forward",
                headway_minutes=10,
                total_trips_per_day=1,
                first_trip_start="06:00:00",
            ),
            ImportTripPattern(
                route_ref="route-b",
                direction="forward",
                headway_minutes=10,
                total_trips_per_day=1,
                first_trip_start="06:00:00",
            ),
        ),
        trip_stop_times={
            ("route-a", "forward"): (
                ImportStopTime(stop_ref="a-s1", sequence=1, arrival_offset_s=0, departure_offset_s=0),
            ),
            ("route-b", "forward"): (
                ImportStopTime(stop_ref="b-s1", sequence=1, arrival_offset_s=0, departure_offset_s=0),
            ),
        },
    )

    scoped = dataset_for_route(combined, "route-a")
    assert [r.ref for r in scoped.routes] == ["route-a"]
    assert [a.name for a in scoped.agencies] == ["Agency A"]
    assert [s.ref for s in scoped.stops] == ["a-s1"]
    assert [rs.route_ref for rs in scoped.route_stops] == ["route-a"]
    assert [p.route_ref for p in scoped.trip_patterns] == ["route-a"]
    assert set(scoped.trip_stop_times.keys()) == {("route-a", "forward")}


def test_dataset_for_route_raises_for_unknown_ref():
    dataset = _synthetic_dataset("Agency X", "r1", "R-1")
    with pytest.raises(ValueError):
        dataset_for_route(dataset, "not-a-real-ref")


# ---------------------------------------------------------------------------
# seeding.trip_generator.generate_daily_trips - synthetic dataset, real DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_daily_trips_creates_expected_count_and_offsets(db_session):
    agency_name = f"Trip Gen Agency {uuid.uuid4()}"
    route, dataset = await _make_already_imported_route(db_session, agency_name, "SYN-1")

    report = await generate_daily_trips(
        db_session, route, agency_name, date(2026, 9, 1), dataset=dataset
    )

    assert report.trips_created == 3  # total_trips_per_day
    assert report.trips_replaced == 0
    assert report.stop_times_created == 6  # 3 trips x 2 stops
    # No new agency/stop/route/route_stop rows - they already existed.
    assert report.agencies_created == 0
    assert report.stops_created == 0
    assert report.routes_created == 0
    assert report.route_stops_created == 0

    trips = (
        await db_session.execute(
            select(Trip).where(Trip.route_id == route.id).order_by(Trip.scheduled_start_time)
        )
    ).scalars().all()
    assert len(trips) == 3
    # `scheduled_start_time` round-trips through Postgres as UTC (see
    # `seeding.importer.trip_id_for`'s docstring) - convert back to PKT
    # (the timezone `first_trip_start` is interpreted in) before
    # comparing wall-clock times.
    from datetime import timedelta, timezone

    pkt = timezone(timedelta(hours=5))
    starts = [t.scheduled_start_time.astimezone(pkt).strftime("%H:%M:%S") for t in trips]
    assert starts == ["06:00:00", "06:30:00", "07:00:00"]

    stop_times = (
        await db_session.execute(
            select(StopTime)
            .where(StopTime.trip_id == trips[0].id)
            .order_by(StopTime.sequence)
        )
    ).scalars().all()
    assert [(st.sequence, st.arrival_offset_s, st.departure_offset_s) for st in stop_times] == [
        (1, 0, 0),
        (2, 300, 300),
    ]


@pytest.mark.asyncio
async def test_generate_daily_trips_is_idempotent(db_session):
    agency_name = f"Trip Gen Agency {uuid.uuid4()}"
    route, dataset = await _make_already_imported_route(db_session, agency_name, "SYN-2")
    service_date = date(2026, 9, 1)

    first = await generate_daily_trips(db_session, route, agency_name, service_date, dataset=dataset)
    assert first.trips_created == 3
    assert first.trips_replaced == 0

    second = await generate_daily_trips(db_session, route, agency_name, service_date, dataset=dataset)
    assert second.trips_created == 3
    assert second.trips_replaced == 3  # replaced in place, not duplicated

    trips = (
        await db_session.execute(select(Trip).where(Trip.route_id == route.id))
    ).scalars().all()
    assert len(trips) == 3  # still exactly 3, not 6


@pytest.mark.asyncio
async def test_generate_daily_trips_different_service_dates_do_not_collide(db_session):
    agency_name = f"Trip Gen Agency {uuid.uuid4()}"
    route, dataset = await _make_already_imported_route(db_session, agency_name, "SYN-3")

    await generate_daily_trips(db_session, route, agency_name, date(2026, 9, 1), dataset=dataset)
    await generate_daily_trips(db_session, route, agency_name, date(2026, 9, 2), dataset=dataset)

    trips = (
        await db_session.execute(select(Trip).where(Trip.route_id == route.id))
    ).scalars().all()
    assert len(trips) == 6  # 3 for each of the two distinct days
    dates_seen = {t.scheduled_start_time.date() for t in trips}
    assert dates_seen == {date(2026, 9, 1), date(2026, 9, 2)}


@pytest.mark.asyncio
async def test_generate_daily_trips_raises_when_route_has_no_pattern(db_session):
    agency_name = f"Trip Gen Agency {uuid.uuid4()}"
    # A dataset that knows the agency/route but has NO trip_patterns for
    # it (e.g. Red Line's real shape: real stops, no researched timetable).
    dataset = ImportDataset(
        agencies=(ImportAgency(name=agency_name),),
        routes=(ImportRoute(ref="no-pattern", agency=agency_name, short_name="NO-PATTERN"),),
    )
    route = Route(short_name="NO-PATTERN")

    with pytest.raises(NoCanonicalTripPattern):
        await generate_daily_trips(
            db_session, route, agency_name, date(2026, 9, 1), dataset=dataset
        )


@pytest.mark.asyncio
async def test_generate_daily_trips_raises_when_route_not_in_dataset_at_all(db_session):
    dataset = _synthetic_dataset("Some Other Agency", "r1", "R-1")
    route = Route(short_name="TOTALLY-UNKNOWN-ROUTE")

    with pytest.raises(NoCanonicalTripPattern):
        await generate_daily_trips(
            db_session, route, "Some Other Agency", date(2026, 9, 1), dataset=dataset
        )


# ---------------------------------------------------------------------------
# POST /admin/trips/generate - HTTP level, synthetic dataset (monkeypatched
# default dataset path so the endpoint's own "load the real file" default
# isn't exercised here - see the REAL-dataset tests below for that).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_trips_endpoint_404_for_nonexistent_route(client):
    response = await client.post(
        "/api/admin/trips/generate",
        json={"route_id": str(uuid.uuid4()), "service_date": "2026-09-01"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_generate_trips_endpoint_404_for_route_without_pattern(client, db_session):
    """Uses the REAL default dataset (the endpoint's default, unmocked
    path) against a route that genuinely has no canonical pattern in it -
    Red Line, which has real stops/route_stops but no researched
    timetable (see docs/transit_data.json)."""
    real_dataset = load_transit_data(DEFAULT_TRANSIT_DATA_PATH)
    await import_dataset(
        db_session, real_dataset, allow_routes_without_stops=True, service_date=date(2026, 9, 1)
    )
    red_line = (
        await db_session.execute(select(Route).where(Route.short_name == "Red"))
    ).scalar_one_or_none()
    assert red_line is not None, "fixture assumption: real dataset has a 'Red' route"

    response = await client.post(
        "/api/admin/trips/generate",
        json={"route_id": str(red_line.id), "service_date": "2026-09-08"},
    )
    assert response.status_code == 404
    assert "no canonical trip pattern" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_generate_trips_endpoint_rejects_malformed_request(client):
    response = await client.post(
        "/api/admin/trips/generate",
        json={"route_id": "not-a-uuid", "service_date": "2026-09-01"},
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Against the REAL docs/transit_data.json - the plan's own acceptance
# check: "Generate trips for FR-04. Verify correct count (97)."
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_trips_endpoint_fr04_matches_real_canonical_pattern_count(
    client, db_session
):
    real_dataset = load_transit_data(DEFAULT_TRANSIT_DATA_PATH)
    fr04_pattern = next(p for p in real_dataset.trip_patterns if p.route_ref == "fr_04")
    # This IS the plan's literal acceptance number - asserted against the
    # live dataset rather than hardcoded, so this test fails loudly (not
    # silently) if docs/transit_data.json's FR-04 pattern ever changes.
    assert fr04_pattern.total_trips_per_day == 97

    await import_dataset(
        db_session, real_dataset, allow_routes_without_stops=True, service_date=date(2026, 9, 1)
    )
    fr04_route = (
        await db_session.execute(select(Route).where(Route.short_name == "FR-04"))
    ).scalar_one()

    # A DIFFERENT service_date than the one used above - this is
    # specifically the "admin generates another day's trips for an
    # already-imported route" scenario Phase 5 adds, not a re-import.
    response = await client.post(
        "/api/admin/trips/generate",
        json={"route_id": str(fr04_route.id), "service_date": "2026-09-15"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route_short_name"] == "FR-04"
    assert body["trips_created"] == 97
    assert body["trips_replaced"] == 0
    assert body["stop_times_created"] == 97 * 25  # 25 stops per FR-04 trip

    trip_count = (
        await db_session.execute(
            select(sa.func.count())
            .select_from(Trip)
            .where(
                Trip.route_id == fr04_route.id,
                sa.func.date(Trip.scheduled_start_time) == date(2026, 9, 15),
            )
        )
    ).scalar_one()
    assert trip_count == 97


@pytest.mark.asyncio
async def test_generate_trips_endpoint_is_idempotent_over_http(client, db_session):
    real_dataset = load_transit_data(DEFAULT_TRANSIT_DATA_PATH)
    await import_dataset(
        db_session, real_dataset, allow_routes_without_stops=True, service_date=date(2026, 9, 1)
    )
    fr01_route = (
        await db_session.execute(select(Route).where(Route.short_name == "FR-01"))
    ).scalar_one()

    first = await client.post(
        "/api/admin/trips/generate",
        json={"route_id": str(fr01_route.id), "service_date": "2026-09-20"},
    )
    second = await client.post(
        "/api/admin/trips/generate",
        json={"route_id": str(fr01_route.id), "service_date": "2026-09-20"},
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["trips_created"] == second.json()["trips_created"]
    assert second.json()["trips_replaced"] == second.json()["trips_created"]

    trip_count = (
        await db_session.execute(
            select(sa.func.count())
            .select_from(Trip)
            .where(
                Trip.route_id == fr01_route.id,
                sa.func.date(Trip.scheduled_start_time) == date(2026, 9, 20),
            )
        )
    ).scalar_one()
    assert trip_count == first.json()["trips_created"]
