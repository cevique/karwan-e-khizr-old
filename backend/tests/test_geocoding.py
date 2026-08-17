"""
Phase 2 tests (plan.md section M): geospatial enrichment of stops with
null coordinates via Nominatim geocoding.

Three layers:

1. Pure `seeding.geocoding` logic (no network, no database):
   - bounding-box validation, query-variant construction
   - `NominatimGeocoder` against a mocked HTTP transport
     (`httpx.MockTransport` - no real network access, matching plan.md
     section L's "mocked Nominatim responses")

2. Import-time provenance (real PostgreSQL/PostGIS, rolled back on
   teardown): stops created WITH coordinates get tagged
   `coordinate_source="SEED_DATUM"` and the dataset's own
   `coordinate_confidence`; stops created without coordinates get no
   provenance yet.

3. `scripts.geocode_stops.geocode_null_coordinate_stops` against a fake
   `Geocoder` (real database, no real network): only null-location stops
   are queried and updated; located stops are left untouched; a
   successful match is tagged NOMINATIM/APPROXIMATE; a failed one is
   tagged UNKNOWN with `location` still NULL; `--dry-run`/`--limit`
   behave as documented.
"""

import os
import uuid

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from core.config import settings  # noqa: E402
from db.models import Stop  # noqa: E402
from seeding.geocoding import (  # noqa: E402
    BBOX_MAX_LAT,
    BBOX_MAX_LON,
    BBOX_MIN_LAT,
    BBOX_MIN_LON,
    GeocodeResult,
    GeocodingError,
    NominatimGeocoder,
    geocode_stop_name,
    in_bounding_box,
    query_variants,
)
from seeding.import_schema import ImportAgency, ImportDataset, ImportStop
from seeding.importer import import_dataset

# ---------------------------------------------------------------------------
# Pure: bounding box / query variants
# ---------------------------------------------------------------------------


def test_in_bounding_box_accepts_islamabad_rawalpindi_area():
    assert in_bounding_box(33.7, 73.05) is True
    assert in_bounding_box(BBOX_MIN_LAT, BBOX_MIN_LON) is True
    assert in_bounding_box(BBOX_MAX_LAT, BBOX_MAX_LON) is True


def test_in_bounding_box_rejects_outside_area():
    assert in_bounding_box(24.86, 67.0) is False  # Karachi
    assert in_bounding_box(31.5, 74.35) is False  # Lahore
    assert in_bounding_box(33.7, 74.5) is False  # east of the box


def test_query_variants_tries_islamabad_then_rawalpindi():
    variants = query_variants("Faizabad")
    assert variants == (
        "Faizabad, Islamabad, Pakistan",
        "Faizabad, Rawalpindi, Pakistan",
    )


# ---------------------------------------------------------------------------
# Pure: NominatimGeocoder against a mocked HTTP transport
# ---------------------------------------------------------------------------


def _nominatim_payload(*candidates: tuple[float, float, str]) -> list[dict]:
    return [
        {"lat": str(lat), "lon": str(lon), "display_name": name} for lat, lon, name in candidates
    ]


@pytest.mark.asyncio
async def test_nominatim_geocoder_returns_in_bounds_match():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == "Faizabad, Islamabad, Pakistan"
        return httpx.Response(
            200, json=_nominatim_payload((33.66, 73.06, "Faizabad, Islamabad, Pakistan"))
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with NominatimGeocoder(client, min_interval_s=0) as geocoder:
        result = await geocoder.geocode("Faizabad, Islamabad, Pakistan")

    assert result == GeocodeResult(
        latitude=33.66, longitude=73.06, display_name="Faizabad, Islamabad, Pakistan"
    )


@pytest.mark.asyncio
async def test_nominatim_geocoder_returns_none_when_no_candidates():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    async with NominatimGeocoder(client, min_interval_s=0) as geocoder:
        result = await geocoder.geocode("Nonexistent Place, Islamabad, Pakistan")

    assert result is None


@pytest.mark.asyncio
async def test_nominatim_geocoder_skips_out_of_bounds_candidates():
    """A wrong-city same-name match (e.g. a "Bank Road" in Lahore) must
    not be accepted just because it's the first result - only an
    in-bounds candidate counts, and later in-bounds candidates are
    checked even if an earlier one was rejected."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_nominatim_payload(
                (31.5, 74.35, "Bank Road, Lahore, Pakistan"),  # out of bounds
                (33.6, 73.05, "Bank Road, Rawalpindi, Pakistan"),  # in bounds
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with NominatimGeocoder(client, min_interval_s=0) as geocoder:
        result = await geocoder.geocode("Bank Road, Pakistan")

    assert result is not None
    assert result.display_name == "Bank Road, Rawalpindi, Pakistan"


@pytest.mark.asyncio
async def test_nominatim_geocoder_returns_none_when_all_candidates_out_of_bounds():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json=_nominatim_payload((24.86, 67.0, "Karachi place")))
        )
    )
    async with NominatimGeocoder(client, min_interval_s=0) as geocoder:
        result = await geocoder.geocode("Some Stop, Pakistan")

    assert result is None


@pytest.mark.asyncio
async def test_nominatim_geocoder_raises_geocoding_error_on_http_failure():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(503, text="Service Unavailable"))
    )
    async with NominatimGeocoder(client, min_interval_s=0) as geocoder:
        with pytest.raises(GeocodingError):
            await geocoder.geocode("Some Stop, Pakistan")


@pytest.mark.asyncio
async def test_nominatim_geocoder_throttles_between_requests():
    import time

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    )
    async with NominatimGeocoder(client, min_interval_s=0.1) as geocoder:
        start = time.monotonic()
        await geocoder.geocode("A, Islamabad, Pakistan")
        await geocoder.geocode("B, Islamabad, Pakistan")
        elapsed = time.monotonic() - start

    assert elapsed >= 0.1


@pytest.mark.asyncio
async def test_geocode_stop_name_falls_back_to_rawalpindi_variant():
    class RecordingFakeGeocoder:
        def __init__(self):
            self.queries: list[str] = []

        async def geocode(self, query):
            self.queries.append(query)
            if "Rawalpindi" in query:
                return GeocodeResult(latitude=33.6, longitude=73.05, display_name=query)
            return None

    geocoder = RecordingFakeGeocoder()
    result = await geocode_stop_name(geocoder, "Bank Road")

    assert result is not None
    assert geocoder.queries == [
        "Bank Road, Islamabad, Pakistan",
        "Bank Road, Rawalpindi, Pakistan",
    ]


@pytest.mark.asyncio
async def test_geocode_stop_name_returns_none_when_no_variant_matches():
    class AlwaysNoneGeocoder:
        async def geocode(self, query):
            return None

    result = await geocode_stop_name(AlwaysNoneGeocoder(), "Nowhere")
    assert result is None


# ---------------------------------------------------------------------------
# Integration: real PostgreSQL/PostGIS, rolled back on teardown
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


class FakeGeocoder:
    """Deterministic `Geocoder` for tests: returns a canned result per
    exact query string, and records every query it was asked."""

    def __init__(self, responses: dict[str, GeocodeResult]):
        self._responses = responses
        self.queries: list[str] = []

    async def geocode(self, query: str) -> GeocodeResult | None:
        self.queries.append(query)
        return self._responses.get(query)


def _dataset_with_stops(agency_name: str, stops: tuple[ImportStop, ...]) -> ImportDataset:
    # No routes: these tests only care about Stop rows and their
    # coordinate provenance, and a route with no route_stops would fail
    # validation (`insufficient_stops`) unless
    # `allow_routes_without_stops=True` were threaded through everywhere.
    return ImportDataset(agencies=(ImportAgency(name=agency_name),), stops=stops)


@pytest.mark.asyncio
async def test_import_tags_located_stop_seed_datum(db_session):
    agency_name = f"Geocode Test Agency {uuid.uuid4()}"
    await import_dataset(
        db_session,
        _dataset_with_stops(
            agency_name,
            (
                ImportStop(
                    ref=f"located-{uuid.uuid4()}",
                    name="Located Stop",
                    latitude=33.7,
                    longitude=73.05,
                    confidence="APPROXIMATE",
                ),
            ),
        ),
    )

    stop = (
        await db_session.execute(select(Stop).where(Stop.name == "Located Stop"))
    ).scalar_one()
    assert stop.coordinate_source == "SEED_DATUM"
    assert stop.coordinate_confidence == "APPROXIMATE"


@pytest.mark.asyncio
async def test_import_leaves_unlocated_stop_without_provenance(db_session):
    agency_name = f"Geocode Test Agency {uuid.uuid4()}"
    await import_dataset(
        db_session,
        _dataset_with_stops(
            agency_name,
            (ImportStop(ref=f"null-{uuid.uuid4()}", name="Null Coord Stop", confidence="OFFICIAL"),),
        ),
    )

    stop = (
        await db_session.execute(select(Stop).where(Stop.name == "Null Coord Stop"))
    ).scalar_one()
    assert stop.location is None
    assert stop.coordinate_source is None
    assert stop.coordinate_confidence is None


@pytest.mark.asyncio
async def test_geocode_null_coordinate_stops_updates_only_null_stops(db_session):
    from scripts.geocode_stops import geocode_null_coordinate_stops

    agency_name = f"Geocode Test Agency {uuid.uuid4()}"
    await import_dataset(
        db_session,
        _dataset_with_stops(
            agency_name,
            (
                ImportStop(
                    ref=f"located-{uuid.uuid4()}",
                    name="Already Located",
                    latitude=33.7,
                    longitude=73.05,
                    confidence="APPROXIMATE",
                ),
                ImportStop(ref=f"resolvable-{uuid.uuid4()}", name="Resolvable Stop"),
                ImportStop(ref=f"unresolvable-{uuid.uuid4()}", name="Unresolvable Stop"),
            ),
        ),
    )

    geocoder = FakeGeocoder(
        {
            "Resolvable Stop, Islamabad, Pakistan": GeocodeResult(
                latitude=33.68, longitude=73.07, display_name="Resolvable Stop, Islamabad"
            ),
        }
    )
    stats = await geocode_null_coordinate_stops(db_session, geocoder)

    assert stats == {"total": 2, "geocoded": 1, "unresolved": 1}

    already_located = (
        await db_session.execute(select(Stop).where(Stop.name == "Already Located"))
    ).scalar_one()
    assert already_located.coordinate_source == "SEED_DATUM"
    # The already-located stop's name was never even queried.
    assert not any(q.startswith("Already Located") for q in geocoder.queries)

    resolved = (
        await db_session.execute(select(Stop).where(Stop.name == "Resolvable Stop"))
    ).scalar_one()
    assert resolved.coordinate_source == "NOMINATIM"
    assert resolved.coordinate_confidence == "APPROXIMATE"
    lon, lat = (
        await db_session.execute(
            sa.text(
                "SELECT ST_X(location::geometry), ST_Y(location::geometry) "
                "FROM stops WHERE id = :id"
            ),
            {"id": resolved.id},
        )
    ).one()
    assert lat == pytest.approx(33.68)
    assert lon == pytest.approx(73.07)

    unresolved = (
        await db_session.execute(select(Stop).where(Stop.name == "Unresolvable Stop"))
    ).scalar_one()
    assert unresolved.location is None
    assert unresolved.coordinate_source is None
    assert unresolved.coordinate_confidence == "UNKNOWN"


@pytest.mark.asyncio
async def test_geocode_null_coordinate_stops_dry_run_writes_nothing(db_session):
    from scripts.geocode_stops import geocode_null_coordinate_stops

    agency_name = f"Geocode Test Agency {uuid.uuid4()}"
    await import_dataset(
        db_session,
        _dataset_with_stops(
            agency_name, (ImportStop(ref=f"dry-{uuid.uuid4()}", name="Dry Run Stop"),)
        ),
    )

    geocoder = FakeGeocoder(
        {
            "Dry Run Stop, Islamabad, Pakistan": GeocodeResult(
                latitude=33.68, longitude=73.07, display_name="Dry Run Stop"
            ),
        }
    )
    stats = await geocode_null_coordinate_stops(db_session, geocoder, dry_run=True)
    assert stats == {"total": 1, "geocoded": 1, "unresolved": 0}

    stop = (
        await db_session.execute(select(Stop).where(Stop.name == "Dry Run Stop"))
    ).scalar_one()
    assert stop.location is None
    assert stop.coordinate_source is None
    assert stop.coordinate_confidence is None


@pytest.mark.asyncio
async def test_geocode_null_coordinate_stops_respects_limit(db_session):
    from scripts.geocode_stops import geocode_null_coordinate_stops

    agency_name = f"Geocode Test Agency {uuid.uuid4()}"
    await import_dataset(
        db_session,
        _dataset_with_stops(
            agency_name,
            tuple(
                ImportStop(ref=f"limit-{uuid.uuid4()}", name=f"Limit Stop {i}") for i in range(3)
            ),
        ),
    )

    stats = await geocode_null_coordinate_stops(db_session, FakeGeocoder({}), limit=2)
    assert stats["total"] == 2
