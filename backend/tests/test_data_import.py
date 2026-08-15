"""
Tests for `seeding.parsers` (JSON/CSV -> ImportDataset, no database) and
`seeding.importer` (ImportDataset -> database rows, real PostgreSQL/
PostGIS, rolled back on teardown - see `db_session` fixture below, copied
from `tests/test_transit_models.py`'s fixture of the same name per this
project's per-file-fixture convention).
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
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from core.config import settings  # noqa: E402
from db.models import Agency, Route, RouteStop, Stop  # noqa: E402
from seeding.import_schema import (  # noqa: E402
    ImportAgency,
    ImportDataset,
    ImportRoute,
    ImportRouteStop,
    ImportStop,
)
import seeding.importer as importer_module  # noqa: E402
from seeding.importer import (  # noqa: E402
    ImportPersistenceError,
    ImportValidationError,
    import_dataset,
)
from seeding.parsers import (  # noqa: E402
    ImportParseError,
    parse_csv_dataset,
    parse_json_dataset,
    parse_json_text,
)

# ---------------------------------------------------------------------------
# Parsers - pure, no database
# ---------------------------------------------------------------------------


def test_parse_json_text_success():
    dataset = parse_json_text(
        """
        {
          "agencies": [{"name": "A", "network_type": "brt"}],
          "stops": [
            {"ref": "s1", "name": "Stop 1", "latitude": 33.7, "longitude": 73.05},
            {"ref": "s2", "name": "Stop 2", "latitude": 33.71, "longitude": 73.06}
          ],
          "routes": [{"ref": "r1", "agency": "A", "short_name": "T-1"}],
          "route_stops": [
            {"route_ref": "r1", "stop_ref": "s1", "sequence": 1},
            {"route_ref": "r1", "stop_ref": "s2", "sequence": 2}
          ]
        }
        """
    )
    assert len(dataset.agencies) == 1
    assert len(dataset.stops) == 2
    assert len(dataset.routes) == 1
    assert len(dataset.route_stops) == 2
    assert dataset.stops[0].latitude == 33.7


def test_parse_json_dataset_defaults_missing_keys_to_empty():
    dataset = parse_json_dataset({"agencies": [{"name": "Solo Agency"}]})
    assert len(dataset.agencies) == 1
    assert dataset.stops == ()
    assert dataset.routes == ()
    assert dataset.route_stops == ()


def test_parse_json_text_rejects_malformed_json_syntax():
    with pytest.raises(ImportParseError):
        parse_json_text("{not valid json")


def test_parse_json_dataset_rejects_non_object_document():
    with pytest.raises(ImportParseError):
        parse_json_dataset([{"name": "not an object at the top level"}])


def test_parse_json_dataset_rejects_missing_required_field():
    with pytest.raises(ImportParseError):
        parse_json_dataset({"stops": [{"ref": "s1", "latitude": 33.7, "longitude": 73.0}]})


def test_parse_json_dataset_rejects_wrong_type_for_coordinate():
    with pytest.raises(ImportParseError):
        parse_json_dataset(
            {
                "stops": [
                    {
                        "ref": "s1",
                        "name": "Bad",
                        "latitude": "not-a-number",
                        "longitude": 73.0,
                    }
                ]
            }
        )


def test_parse_csv_dataset_success():
    dataset = parse_csv_dataset(
        agencies_csv="name,network_type\nA,brt\n",
        stops_csv=(
            "ref,name,latitude,longitude\n"
            "s1,Stop 1,33.7,73.05\n"
            "s2,Stop 2,33.71,73.06\n"
        ),
        routes_csv="ref,agency,short_name,long_name,color\nr1,A,T-1,Test Route,#FF0000\n",
        route_stops_csv=(
            "route_ref,stop_ref,sequence,distance_along_route_m\n"
            "r1,s1,1,0\n"
            "r1,s2,2,500\n"
        ),
    )
    assert len(dataset.agencies) == 1
    assert dataset.routes[0].long_name == "Test Route"
    assert dataset.route_stops[1].distance_along_route_m == 500.0


def test_parse_csv_dataset_allows_missing_optional_columns():
    dataset = parse_csv_dataset(
        agencies_csv="name\nA\n",
        stops_csv="ref,name,latitude,longitude\ns1,Stop 1,33.7,73.05\n",
    )
    assert dataset.agencies[0].network_type is None
    assert dataset.routes == ()
    assert dataset.route_stops == ()


def test_parse_csv_dataset_rejects_missing_required_column():
    with pytest.raises(ImportParseError):
        parse_csv_dataset(stops_csv="ref,name,latitude\ns1,Stop 1,33.7\n")


def test_parse_csv_dataset_rejects_extra_column_row():
    with pytest.raises(ImportParseError):
        parse_csv_dataset(
            stops_csv=(
                "ref,name,latitude,longitude\n"
                "s1,Stop 1,33.7,73.05,extra-value\n"
            )
        )


def test_parse_csv_dataset_rejects_non_integer_sequence():
    with pytest.raises(ImportParseError):
        parse_csv_dataset(
            route_stops_csv=(
                "route_ref,stop_ref,sequence\nr1,s1,not-an-int\n"
            )
        )


# ---------------------------------------------------------------------------
# Importer - real database, rolled back on teardown
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
    """A real AsyncSession bound to the application's own DATABASE_URL,
    nested inside an outer transaction that is always rolled back on
    teardown (SAVEPOINT pattern) - see `tests/test_transit_models.py`'s
    fixture of the same name."""
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


def _small_dataset(agency_name: str, stop_prefix: str, route_short_name: str) -> ImportDataset:
    return ImportDataset(
        agencies=(ImportAgency(name=agency_name, network_type="test"),),
        stops=(
            ImportStop(ref="s1", name=f"{stop_prefix} A", latitude=33.70, longitude=73.05),
            ImportStop(ref="s2", name=f"{stop_prefix} B", latitude=33.71, longitude=73.06),
        ),
        routes=(ImportRoute(ref="r1", agency=agency_name, short_name=route_short_name),),
        route_stops=(
            ImportRouteStop(route_ref="r1", stop_ref="s1", sequence=1),
            ImportRouteStop(route_ref="r1", stop_ref="s2", sequence=2),
        ),
    )


@pytest.mark.asyncio
async def test_import_dataset_creates_all_entities(db_session):
    agency_name = f"Import Test Agency {uuid.uuid4()}"
    dataset = _small_dataset(agency_name, "Import Stop", "IT-1")

    report = await import_dataset(db_session, dataset)

    assert report.agencies_created == 1
    assert report.stops_created == 2
    assert report.routes_created == 1
    assert report.route_stops_created == 2

    agency = (
        await db_session.execute(select(Agency).where(Agency.name == agency_name))
    ).scalar_one()
    routes = (
        await db_session.execute(select(Route).where(Route.agency_id == agency.id))
    ).scalars().all()
    assert len(routes) == 1
    route_stops = (
        await db_session.execute(
            select(RouteStop).where(RouteStop.route_id == routes[0].id)
        )
    ).scalars().all()
    assert len(route_stops) == 2


@pytest.mark.asyncio
async def test_import_dataset_preserves_relationships(db_session):
    """The imported RouteStop rows point at the correct Stop rows (by
    ref -> name -> DB row), in the declared sequence order."""
    from sqlalchemy.orm import selectinload

    agency_name = f"Import Rel Agency {uuid.uuid4()}"
    dataset = _small_dataset(agency_name, "Import Rel Stop", "IR-1")

    await import_dataset(db_session, dataset)

    route = (
        await db_session.execute(
            select(Route)
            .options(selectinload(Route.route_stops).selectinload(RouteStop.stop))
            .join(Agency)
            .where(Agency.name == agency_name)
        )
    ).scalar_one()
    ordered_stop_names = [rs.stop.name for rs in sorted(route.route_stops, key=lambda rs: rs.sequence)]
    assert ordered_stop_names == ["Import Rel Stop A", "Import Rel Stop B"]


@pytest.mark.asyncio
async def test_import_dataset_rejects_invalid_dataset_without_writing(db_session):
    agency_name = f"Invalid Import Agency {uuid.uuid4()}"
    dataset = ImportDataset(
        agencies=(ImportAgency(name=agency_name),),
        stops=(ImportStop(ref="s1", name="Only One Stop", latitude=33.7, longitude=73.0),),
        routes=(ImportRoute(ref="r1", agency=agency_name, short_name="INV-1"),),
        route_stops=(ImportRouteStop(route_ref="r1", stop_ref="s1", sequence=1),),
    )

    with pytest.raises(ImportValidationError) as excinfo:
        await import_dataset(db_session, dataset)

    assert "insufficient_stops" in {e.code for e in excinfo.value.result.errors}

    existing = (
        await db_session.execute(select(Agency).where(Agency.name == agency_name))
    ).scalar_one_or_none()
    assert existing is None


@pytest.mark.asyncio
async def test_import_dataset_upsert_updates_existing_rows(db_session):
    agency_name = f"Upsert Agency {uuid.uuid4()}"
    first = _small_dataset(agency_name, "Upsert Stop", "UP-1")
    await import_dataset(db_session, first)

    second = ImportDataset(
        agencies=(ImportAgency(name=agency_name, network_type="test"),),
        stops=(
            ImportStop(ref="s1", name="Upsert Stop A", latitude=40.0, longitude=-70.0),
            ImportStop(ref="s2", name="Upsert Stop B", latitude=33.71, longitude=73.06),
        ),
        routes=(
            ImportRoute(ref="r1", agency=agency_name, short_name="UP-1", color="#00FF00"),
        ),
        route_stops=(
            ImportRouteStop(route_ref="r1", stop_ref="s1", sequence=1),
            ImportRouteStop(route_ref="r1", stop_ref="s2", sequence=2),
        ),
    )
    report = await import_dataset(db_session, second)

    assert report.agencies_created == 0
    assert report.stops_created == 0
    assert report.routes_created == 0
    assert report.route_stops_created == 0
    assert report.stops_updated == 1
    assert report.routes_updated == 1

    moved_stop = (
        await db_session.execute(select(Stop).where(Stop.name == "Upsert Stop A"))
    ).scalar_one()
    lon, lat = (
        await db_session.execute(
            sa.text(
                "SELECT ST_X(location::geometry), ST_Y(location::geometry) "
                "FROM stops WHERE id = :id"
            ),
            {"id": moved_stop.id},
        )
    ).one()
    assert lat == pytest.approx(40.0, abs=1e-4)
    assert lon == pytest.approx(-70.0, abs=1e-4)


@pytest.mark.asyncio
async def test_import_dataset_second_identical_import_is_a_no_op(db_session):
    """Re-running the exact same import is safely repeatable: nothing
    created, nothing reported as updated the second time."""
    agency_name = f"Repeat Import Agency {uuid.uuid4()}"
    dataset = _small_dataset(agency_name, "Repeat Stop", "RP-1")

    await import_dataset(db_session, dataset)
    second_report = await import_dataset(db_session, dataset)

    assert second_report.agencies_created == 0
    assert second_report.stops_created == 0
    assert second_report.routes_created == 0
    assert second_report.route_stops_created == 0
    assert second_report.agencies_updated == 0
    assert second_report.stops_updated == 0
    assert second_report.routes_updated == 0
    assert second_report.route_stops_updated == 0


@pytest.mark.asyncio
async def test_import_dataset_rolls_back_all_writes_on_persistence_failure(
    db_session, monkeypatch
):
    """Simulates a failure partway through persistence (after the
    Agency/Stop rows for this import were already created, but before
    RouteStop creation finishes) and confirms the whole import - not
    just the failing statement - is rolled back: nothing from this
    dataset is visible afterward, even within this same session."""
    agency_name = f"Rollback Agency {uuid.uuid4()}"
    dataset = _small_dataset(agency_name, "Rollback Stop", "RB-1")

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated persistence failure")

    monkeypatch.setattr(importer_module, "_get_or_create_route_stop", _boom)

    with pytest.raises(ImportPersistenceError):
        await import_dataset(db_session, dataset)

    existing_agency = (
        await db_session.execute(select(Agency).where(Agency.name == agency_name))
    ).scalar_one_or_none()
    assert existing_agency is None

    existing_stop = (
        await db_session.execute(
            select(Stop).where(Stop.name == "Rollback Stop A")
        )
    ).scalar_one_or_none()
    assert existing_stop is None
