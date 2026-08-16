"""
Phase 1 tests (plan.md section M): importing the canonical
`docs/transit_data.json` research dataset.

Two layers:

1. Pure converter/generator tests (no database):
   - `seeding.transit_data_importer.transit_data_to_dataset` maps the
     research JSON shape (uuid ids + human keys, operators, trips with
     embedded stop_times) to the generic `ImportDataset`.
   - `seeding.importer.generate_trip_starts` expands one
     `ImportTripPattern` into its day's `scheduled_start_time`s.
   - `seeding.parsers` parses the optional `trip_patterns` array.

2. Integration tests (real PostgreSQL/PostGIS, rolled back on teardown):
   - full import: transit_data.json -> ImportDataset -> DB rows
   - Trip/StopTime row counts match the documented CDA patterns
   - null-coordinate stops are imported (not fabricated) and excluded
     from the routing graph
   - idempotent re-import (deterministic trip IDs are replaced in place)
"""

import os
from datetime import date, time, timedelta, timezone
from decimal import Decimal

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from core.config import settings  # noqa: E402
from db.models import Route, RouteStop, Stop, StopTime, Trip  # noqa: E402
from seeding.importer import (  # noqa: E402
    ImportValidationError,
    generate_trip_starts,
    import_dataset,
    stop_time_id_for,
    trip_id_for,
)
from seeding.import_schema import (  # noqa: E402
    ImportDataset,
    ImportStopTime,
    ImportTripPattern,
)
from seeding.parsers import ImportParseError, parse_json_dataset  # noqa: E402
from seeding.transit_data_importer import load_transit_data  # noqa: E402
from seeding.validation import validate_dataset  # noqa: E402

TEST_DATASET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs",
    "transit_data.json",
)

SERVICE_DATE = date(2026, 8, 16)
# Postgres stores TIMESTAMPTZ and asyncpg returns it as UTC; the PKT
# wall-clock is what the research documents express.
PKT = timezone(timedelta(hours=5))


# ---------------------------------------------------------------------------
# Pure: transit_data.json -> ImportDataset
# ---------------------------------------------------------------------------


def test_transit_data_to_dataset_maps_research_shape():
    dataset = load_transit_data(TEST_DATASET_PATH)

    assert len(dataset.agencies) == 2
    assert {a.name for a in dataset.agencies} == {
        "Punjab Mass Transit Authority (PMTA)",
        "Capital Development Authority (CDA) / Capital Mass Transit Authority (CMTA)",
    }

    assert len(dataset.stops) == 122
    assert all(s.ref and s.name for s in dataset.stops)
    # The dataset intentionally leaves most stop coordinates null - the
    # converter must carry that through rather than fabricating values.
    assert sum(1 for s in dataset.stops if s.latitude is None) == 105
    assert sum(1 for s in dataset.stops if s.latitude is not None) == 17

    assert len(dataset.routes) == 26
    # Route refs are the human keys; agency is resolved to the operator NAME.
    red_line = next(r for r in dataset.routes if r.ref == "red_line")
    assert red_line.agency == "Punjab Mass Transit Authority (PMTA)"
    assert red_line.short_name == "Red"
    assert red_line.color == "#C62828"

    assert len(dataset.trip_patterns) == 4


def test_transit_data_to_dataset_derives_route_stops_for_fr_routes():
    """The top-level route_stops array only covers red_line (23 rows); the
    4 FR routes carry their ordered stop sequences inside trips[].stop_times,
    so the converter derives RouteStop rows for them."""
    dataset = load_transit_data(TEST_DATASET_PATH)
    grouped = dataset.routes_with_stops()

    assert len(grouped["red_line"]) == 23
    # 26 + 25 + 23 + 18 canonical pattern stops.
    assert len(grouped["fr_01"]) == 26
    assert len(grouped["fr_04"]) == 25
    assert len(grouped["fr_07"]) == 23
    assert len(grouped["fr_14"]) == 18
    # Derived FR sequences are 1-based contiguous.
    assert [rs.sequence for rs in grouped["fr_01"]] == list(range(1, 27))


def test_transit_data_to_dataset_maps_trip_patterns_with_normalized_direction():
    dataset = load_transit_data(TEST_DATASET_PATH)
    by_route_dir = {(p.route_ref, p.direction): p for p in dataset.trip_patterns}

    fr_01 = by_route_dir[("fr_01", "backward")]
    assert fr_01.headway_minutes == 60
    assert fr_01.total_trips_per_day == 16
    assert fr_01.first_trip_start == "07:15:00"
    assert fr_01.last_trip_start == "22:00:00"
    assert fr_01.confidence == "OFFICIAL"

    fr_14 = by_route_dir[("fr_14", "forward")]
    assert fr_14.headway_minutes == 15
    assert fr_14.total_trips_per_day == 65
    assert fr_14.last_trip_start is None

    # FR-14's one null departure_offset_s is treated as "no dwell":
    # departure = arrival for the terminal cda_cda_stop.
    fr_14_times = dataset.stop_times_for("fr_14", "forward")
    cda_cda_stop = [st for st in fr_14_times if st.stop_ref == "cda_cda_stop"]
    assert len(cda_cda_stop) == 1
    assert cda_cda_stop[0].arrival_offset_s == 2875
    assert cda_cda_stop[0].departure_offset_s == 2875


def test_transit_data_import_validates_with_only_warnings():
    """21 of the 26 routes have no stop sequence yet (DATA_GAPS.md). With
    `allow_routes_without_stops=True` those become warnings, not errors."""
    dataset = load_transit_data(TEST_DATASET_PATH)

    strict = validate_dataset(dataset)
    assert not strict.is_valid
    assert sum(1 for e in strict.errors if e.code == "insufficient_stops") == 21

    relaxed = validate_dataset(dataset, allow_routes_without_stops=True)
    assert relaxed.is_valid
    assert not any(e.code == "insufficient_stops" for e in relaxed.errors)
    assert any(e.code == "insufficient_stops" for e in relaxed.warnings)


# ---------------------------------------------------------------------------
# Pure: trip pattern -> daily trip starts
# ---------------------------------------------------------------------------


def test_generate_trip_starts_expands_fr_01_headway():
    pattern = ImportTripPattern(
        route_ref="fr_01",
        direction="backward",
        headway_minutes=60,
        total_trips_per_day=16,
        first_trip_start="07:15:00",
        last_trip_start="22:00:00",
    )
    starts = generate_trip_starts(pattern, SERVICE_DATE)
    assert len(starts) == 16
    assert starts[0].hour == 7 and starts[0].minute == 15
    assert starts[1].hour == 8 and starts[1].minute == 15
    assert starts[-1].hour == 22 and starts[-1].minute == 15


def test_generate_trip_starts_does_not_truncate_to_last_trip_start():
    """FR-01's documented 16th trip starts at 22:15, 15 minutes after its
    stated last_trip_start of 22:00. The documented trip count is
    authoritative - the discrepancy is surfaced as a validation warning
    (see validation), not by silently dropping the trip."""
    pattern = ImportTripPattern(
        route_ref="fr_01",
        direction="backward",
        headway_minutes=60,
        total_trips_per_day=16,
        first_trip_start="07:15:00",
        last_trip_start="22:00:00",
    )
    assert len(generate_trip_starts(pattern, SERVICE_DATE)) == 16


def test_generate_trip_starts_handles_null_last_trip_start():
    pattern = ImportTripPattern(
        route_ref="fr_14",
        direction="forward",
        headway_minutes=15,
        total_trips_per_day=65,
        first_trip_start="06:00:00",
        last_trip_start=None,
    )
    starts = generate_trip_starts(pattern, SERVICE_DATE)
    assert len(starts) == 65
    assert starts[0].hour == 6 and starts[0].minute == 0
    assert starts[-1].hour == 22 and starts[-1].minute == 0


# ---------------------------------------------------------------------------
# Pure: generic JSON parser accepts optional trip_patterns
# ---------------------------------------------------------------------------


def test_parse_json_dataset_parses_trip_patterns():
    dataset = parse_json_dataset(
        {
            "stops": [{"ref": "a", "name": "A", "latitude": 33.7, "longitude": 73.0}],
            "routes": [{"ref": "r1", "agency": "X", "short_name": "R1"}],
            "trip_patterns": [
                {
                    "route_ref": "r1",
                    "direction": "forward",
                    "headway_minutes": 15,
                    "total_trips_per_day": 3,
                    "first_trip_start": "06:00:00",
                    "stop_times": [
                        {
                            "stop_ref": "a",
                            "sequence": 1,
                            "arrival_offset_s": 0,
                            "departure_offset_s": 0,
                        }
                    ],
                }
            ],
        }
    )
    assert len(dataset.trip_patterns) == 1
    pattern = dataset.trip_patterns[0]
    assert pattern.route_ref == "r1"
    assert pattern.total_trips_per_day == 3
    assert dataset.stop_times_for("r1", "forward") == (
        ImportStopTime(stop_ref="a", sequence=1, arrival_offset_s=0, departure_offset_s=0),
    )


def test_parse_json_dataset_rejects_trip_patterns_wrong_type():
    with pytest.raises(ImportParseError):
        parse_json_dataset({"trip_patterns": "not-a-list"})


def test_parse_json_dataset_rejects_bad_trip_pattern_field():
    with pytest.raises(ImportParseError):
        parse_json_dataset(
            {
                "trip_patterns": [
                    {"route_ref": "r1", "headway_minutes": "fast", "total_trips_per_day": 3}
                ]
            }
        )


# ---------------------------------------------------------------------------
# Validation of trip patterns
# ---------------------------------------------------------------------------


def test_validation_reports_trip_pattern_problems():
    dataset = ImportDataset(
        stops=(),
        routes=(),
        route_stops=(),
        trip_patterns=(
            ImportTripPattern(
                route_ref="ghost_route",
                direction="sideways",
                headway_minutes=0,
                total_trips_per_day=0,
                first_trip_start="25:00:00",
            ),
        ),
    )
    result = validate_dataset(dataset, allow_routes_without_stops=True)
    codes = {e.code for e in result.errors}
    assert "missing_route_reference" in codes
    assert "invalid_direction" in codes
    assert "invalid_headway" in codes
    assert "invalid_trip_count" in codes
    assert "invalid_time" in codes
    assert "missing_stop_times" in codes


def test_validation_reports_stop_time_offset_problems():
    from seeding.import_schema import ImportRoute, ImportStop

    dataset = ImportDataset(
        stops=(
            ImportStop(ref="a", name="A", latitude=33.7, longitude=73.0),
        ),
        routes=(
            ImportRoute(ref="r1", agency="X", short_name="R1"),
        ),
        trip_patterns=(
            ImportTripPattern(
                route_ref="r1",
                direction="forward",
                headway_minutes=10,
                total_trips_per_day=2,
                first_trip_start="06:00:00",
            ),
        ),
        trip_stop_times={
            ("r1", "forward"): (
                ImportStopTime(stop_ref="a", sequence=1, arrival_offset_s=0, departure_offset_s=0),
                ImportStopTime(stop_ref="ghost", sequence=2, arrival_offset_s=10, departure_offset_s=5),
            )
        },
    )
    result = validate_dataset(dataset)
    codes = {e.code for e in result.errors}
    assert "missing_stop_reference" in codes
    assert "invalid_offset_ordering" in codes  # departure before arrival
    assert result.is_valid is False


# ---------------------------------------------------------------------------
# Integration: full import into the database (rolled back on teardown)
# ---------------------------------------------------------------------------


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
    """Same savepoint/rollback fixture as the rest of the suite."""
    if not await _database_reachable(settings.DATABASE_URL):
        pytest.skip(
            f"DATABASE_URL ({settings.DATABASE_URL}) is not reachable - "
            "skipping tests that need the real PostgreSQL/PostGIS database"
        )

    from sqlalchemy.ext.asyncio import AsyncSession

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


@pytest.mark.asyncio
async def test_full_import_row_counts(db_session):
    dataset = load_transit_data(TEST_DATASET_PATH)
    report = await import_dataset(
        db_session,
        dataset,
        allow_routes_without_stops=True,
        service_date=SERVICE_DATE,
    )

    assert report.agencies_created == 2
    assert report.stops_created == 122
    assert report.routes_created == 26
    assert report.route_stops_created == 115
    # 16 + 97 + 97 + 65 documented daily trips.
    assert report.trips_created == 275
    # 16*26 + 97*25 + 97*23 + 65*18 stop_times.
    assert report.stop_times_created == 6242

    trip_count = (
        await db_session.execute(select(func.count()).select_from(Trip))
    ).scalar()
    assert trip_count == 275
    stop_time_count = (
        await db_session.execute(select(func.count()).select_from(StopTime))
    ).scalar()
    assert stop_time_count == 6242


@pytest.mark.asyncio
async def test_imported_stops_carry_null_and_non_null_coordinates(db_session):
    await import_dataset(
        db_session,
        load_transit_data(TEST_DATASET_PATH),
        allow_routes_without_stops=True,
        service_date=SERVICE_DATE,
    )

    total = (await db_session.execute(select(func.count()).select_from(Stop))).scalar()
    located = (
        await db_session.execute(
            select(func.count()).select_from(Stop).where(Stop.location.is_not(None))
        )
    ).scalar()
    unlocated = (
        await db_session.execute(
            select(func.count()).select_from(Stop).where(Stop.location.is_(None))
        )
    ).scalar()
    assert total == 122
    assert located == 17
    assert unlocated == 105


@pytest.mark.asyncio
async def test_fr_route_gets_trips_with_canonical_offsets(db_session):
    await import_dataset(
        db_session,
        load_transit_data(TEST_DATASET_PATH),
        allow_routes_without_stops=True,
        service_date=SERVICE_DATE,
    )

    route = (
        await db_session.execute(
            select(Route).where(Route.short_name == "FR-01")
        )
    ).scalar_one()
    trips = (
        await db_session.execute(
            select(Trip).where(Trip.route_id == route.id).order_by(Trip.scheduled_start_time)
        )
    ).scalars().all()
    assert len(trips) == 16
    first_pkt = trips[0].scheduled_start_time.astimezone(PKT)
    assert first_pkt.hour == 7
    assert first_pkt.minute == 15
    assert trips[1].scheduled_start_time.astimezone(PKT).hour == 8

    stop_times = (
        await db_session.execute(
            select(StopTime)
            .where(StopTime.trip_id == trips[0].id)
            .order_by(StopTime.sequence)
        )
    ).scalars().all()
    assert len(stop_times) == 26
    assert stop_times[0].arrival_offset_s == 0
    assert stop_times[0].departure_offset_s == 0
    assert stop_times[1].arrival_offset_s == 168
    assert stop_times[1].departure_offset_s == 188
    assert stop_times[-1].arrival_offset_s == stop_times[-1].departure_offset_s


@pytest.mark.asyncio
async def test_import_idempotent_same_service_date(db_session):
    dataset = load_transit_data(TEST_DATASET_PATH)
    await import_dataset(
        db_session, dataset, allow_routes_without_stops=True, service_date=SERVICE_DATE
    )

    second_report = await import_dataset(
        db_session, dataset, allow_routes_without_stops=True, service_date=SERVICE_DATE
    )

    # Static data: get-or-create, nothing created/updated second time.
    assert second_report.agencies_created == 0
    assert second_report.stops_created == 0
    assert second_report.routes_created == 0
    assert second_report.route_stops_created == 0
    # Trips: all 275 replaced in place by deterministic ID.
    assert second_report.trips_replaced == 275
    assert second_report.trips_created == 275

    trip_count = (
        await db_session.execute(select(func.count()).select_from(Trip))
    ).scalar()
    assert trip_count == 275


@pytest.mark.asyncio
async def test_different_service_date_creates_separate_trips(db_session):
    dataset = load_transit_data(TEST_DATASET_PATH)
    await import_dataset(
        db_session, dataset, allow_routes_without_stops=True, service_date=SERVICE_DATE
    )
    await import_dataset(
        db_session,
        dataset,
        allow_routes_without_stops=True,
        service_date=date(2026, 8, 17),
    )
    trip_count = (
        await db_session.execute(select(func.count()).select_from(Trip))
    ).scalar()
    assert trip_count == 550


@pytest.mark.asyncio
async def test_trip_ids_are_deterministic(db_session):
    dataset = load_transit_data(TEST_DATASET_PATH)
    await import_dataset(
        db_session, dataset, allow_routes_without_stops=True, service_date=SERVICE_DATE
    )
    route = (
        await db_session.execute(select(Route).where(Route.short_name == "FR-01"))
    ).scalar_one()
    trips = (
        await db_session.execute(
            select(Trip).where(Trip.route_id == route.id).order_by(Trip.scheduled_start_time)
        )
    ).scalars().all()

    expected_first = trip_id_for(route.id, "backward", trips[0].scheduled_start_time)
    assert trips[0].id == expected_first

    first_st = (
        await db_session.execute(
            select(StopTime)
            .where(StopTime.trip_id == trips[0].id)
            .order_by(StopTime.sequence)
        )
    ).scalars().first()
    assert first_st.id == stop_time_id_for(trips[0].id, 1)


@pytest.mark.asyncio
async def test_import_requires_service_date_when_trip_patterns_present(db_session):
    dataset = load_transit_data(TEST_DATASET_PATH)
    with pytest.raises(ImportValidationError) as excinfo:
        await import_dataset(
            db_session, dataset, allow_routes_without_stops=True, service_date=None
        )
    assert "missing_service_date" in {e.code for e in excinfo.value.result.errors}


@pytest.mark.asyncio
async def test_routing_graph_skips_unlocated_stops(db_session):
    """The routing graph must not contain nodes for the 105 unlocated
    stops - a stop that can't be positioned has no place in a coordinate
    graph - and must not crash on routes whose stop sequence crosses them."""
    from routing.graph import build_graph

    await import_dataset(
        db_session,
        load_transit_data(TEST_DATASET_PATH),
        allow_routes_without_stops=True,
        service_date=SERVICE_DATE,
    )

    graph = await build_graph(db_session)
    located = (
        await db_session.execute(
            select(func.count()).select_from(Stop).where(Stop.location.is_not(None))
        )
    ).scalar()
    assert len(graph.nodes) == located
    assert all(
        -90 <= node.latitude <= 90 and -180 <= node.longitude <= 180
        for node in graph.nodes.values()
    )


@pytest.mark.asyncio
async def test_build_trip_for_route_rejects_route_with_unlocated_stop(db_session):
    """Demo-trip building needs coordinates for every stop (timing comes
    from distances); a route with an unlocated stop must fail loudly with
    a clear message, not crash with a confusing TypeError."""
    from simulation.trip_builder import build_trip_for_route

    await import_dataset(
        db_session,
        load_transit_data(TEST_DATASET_PATH),
        allow_routes_without_stops=True,
        service_date=SERVICE_DATE,
    )
    route = (
        await db_session.execute(select(Route).where(Route.short_name == "FR-01"))
    ).scalar_one()

    with pytest.raises(ValueError, match="without coordinates"):
        await build_trip_for_route(db_session, route.id)


@pytest.mark.asyncio
async def test_load_trip_schedule_returns_none_when_stops_unlocated(db_session):
    """A generated FR trip whose stops lack coordinates cannot be
    simulated - load_trip_schedule must return None (not raise)."""
    from simulation.trip_builder import load_trip_schedule

    await import_dataset(
        db_session,
        load_transit_data(TEST_DATASET_PATH),
        allow_routes_without_stops=True,
        service_date=SERVICE_DATE,
    )
    trip = (
        await db_session.execute(select(Trip).limit(1))
    ).scalar_one()
    assert await load_trip_schedule(db_session, trip.id) is None


def test_fr_14_stop_times_first_offset_zero():
    dataset = load_transit_data(TEST_DATASET_PATH)
    times = dataset.stop_times_for("fr_14", "forward")
    assert times[0].arrival_offset_s == 0
    assert times[-1].arrival_offset_s == times[-1].departure_offset_s


def test_transit_data_import_stops_are_import_stops():
    dataset = load_transit_data(TEST_DATASET_PATH)
    from seeding.import_schema import ImportStop
    assert isinstance(dataset.stops[0], ImportStop)


def test_route_stops_are_in_sequence_order():
    dataset = load_transit_data(TEST_DATASET_PATH)
    for route_ref, route_stops in dataset.routes_with_stops().items():
        sequences = [rs.sequence for rs in route_stops]
        assert sequences == sorted(sequences), f"{route_ref} not sorted"
        assert sequences == list(range(1, len(sequences) + 1)), f"{route_ref} not contiguous"