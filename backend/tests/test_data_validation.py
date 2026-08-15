"""
Tests for `seeding.validation.validate_dataset` - pure, side-effect-free
logic with no database dependency, so every test here always runs (no
skip-if-database-unreachable needed).
"""

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr",
)
os.environ.setdefault("SECRET_KEY", "test_only_not_a_real_secret")

from seeding.import_schema import (  # noqa: E402
    ImportAgency,
    ImportDataset,
    ImportRoute,
    ImportRouteStop,
    ImportStop,
)
from seeding.validation import validate_dataset  # noqa: E402


def _issue_codes(result, severity=None):
    issues = result.issues if severity is None else (
        result.errors if severity == "error" else result.warnings
    )
    return {issue.code for issue in issues}


def _minimal_valid_dataset() -> ImportDataset:
    """A tiny, entirely valid two-stop, one-route dataset - the baseline
    every "does this ONE thing make it invalid" test below mutates."""
    return ImportDataset(
        agencies=(ImportAgency(name="Test Agency"),),
        stops=(
            ImportStop(ref="s1", name="Stop One", latitude=33.70, longitude=73.05),
            ImportStop(ref="s2", name="Stop Two", latitude=33.71, longitude=73.06),
        ),
        routes=(ImportRoute(ref="r1", agency="Test Agency", short_name="T-1"),),
        route_stops=(
            ImportRouteStop(route_ref="r1", stop_ref="s1", sequence=1),
            ImportRouteStop(route_ref="r1", stop_ref="s2", sequence=2),
        ),
    )


def test_minimal_valid_dataset_has_no_errors():
    result = validate_dataset(_minimal_valid_dataset())
    assert result.is_valid
    assert result.errors == ()


def test_empty_dataset_is_valid():
    """An empty dataset is valid input (nothing to reject) - not the same
    question as "does the seed dataset itself pass validation", which is
    covered in tests/test_seed_data.py."""
    result = validate_dataset(ImportDataset())
    assert result.is_valid


# ---------------------------------------------------------------------------
# Duplicate identifiers
# ---------------------------------------------------------------------------


def test_duplicate_agency_name_is_an_error():
    base = _minimal_valid_dataset()
    dataset = ImportDataset(
        agencies=base.agencies + (ImportAgency(name="Test Agency"),),
        stops=base.stops,
        routes=base.routes,
        route_stops=base.route_stops,
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "duplicate_agency_name" in _issue_codes(result, "error")


def test_duplicate_stop_ref_is_an_error():
    base = _minimal_valid_dataset()
    dataset = ImportDataset(
        agencies=base.agencies,
        stops=base.stops + (ImportStop(ref="s1", name="Dup", latitude=1, longitude=1),),
        routes=base.routes,
        route_stops=base.route_stops,
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "duplicate_stop_ref" in _issue_codes(result, "error")


def test_duplicate_route_ref_is_an_error():
    base = _minimal_valid_dataset()
    dataset = ImportDataset(
        agencies=base.agencies,
        stops=base.stops,
        routes=base.routes
        + (ImportRoute(ref="r1", agency="Test Agency", short_name="T-2"),),
        route_stops=base.route_stops,
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "duplicate_route_ref" in _issue_codes(result, "error")


# ---------------------------------------------------------------------------
# Invalid coordinates / geometry
# ---------------------------------------------------------------------------


def test_out_of_range_latitude_is_an_error():
    dataset = ImportDataset(
        agencies=(ImportAgency(name="A"),),
        stops=(ImportStop(ref="s1", name="Bad", latitude=95.0, longitude=73.0),),
        routes=(),
        route_stops=(),
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "invalid_coordinates" in _issue_codes(result, "error")


def test_out_of_range_longitude_is_an_error():
    dataset = ImportDataset(
        agencies=(ImportAgency(name="A"),),
        stops=(ImportStop(ref="s1", name="Bad", latitude=33.0, longitude=190.0),),
        routes=(),
        route_stops=(),
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "invalid_coordinates" in _issue_codes(result, "error")


def test_non_finite_coordinate_is_an_error():
    dataset = ImportDataset(
        agencies=(),
        stops=(ImportStop(ref="s1", name="Bad", latitude=float("nan"), longitude=73.0),),
        routes=(),
        route_stops=(),
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "invalid_coordinates" in _issue_codes(result, "error")


# ---------------------------------------------------------------------------
# Missing route/stop references
# ---------------------------------------------------------------------------


def test_route_stop_referencing_unknown_stop_is_an_error():
    base = _minimal_valid_dataset()
    dataset = ImportDataset(
        agencies=base.agencies,
        stops=base.stops,
        routes=base.routes,
        route_stops=(
            ImportRouteStop(route_ref="r1", stop_ref="s1", sequence=1),
            ImportRouteStop(route_ref="r1", stop_ref="does-not-exist", sequence=2),
        ),
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "missing_stop_reference" in _issue_codes(result, "error")


def test_route_stop_referencing_unknown_route_is_an_error():
    base = _minimal_valid_dataset()
    dataset = ImportDataset(
        agencies=base.agencies,
        stops=base.stops,
        routes=base.routes,
        route_stops=(
            ImportRouteStop(route_ref="does-not-exist", stop_ref="s1", sequence=1),
            ImportRouteStop(route_ref="does-not-exist", stop_ref="s2", sequence=2),
        ),
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "missing_route_reference" in _issue_codes(result, "error")


# ---------------------------------------------------------------------------
# Duplicate / invalid sequence
# ---------------------------------------------------------------------------


def test_duplicate_route_stop_sequence_is_an_error():
    base = _minimal_valid_dataset()
    dataset = ImportDataset(
        agencies=base.agencies,
        stops=base.stops,
        routes=base.routes,
        route_stops=(
            ImportRouteStop(route_ref="r1", stop_ref="s1", sequence=1),
            ImportRouteStop(route_ref="r1", stop_ref="s2", sequence=1),
        ),
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "duplicate_route_stop_sequence" in _issue_codes(result, "error")


def test_non_positive_sequence_is_an_error():
    base = _minimal_valid_dataset()
    dataset = ImportDataset(
        agencies=base.agencies,
        stops=base.stops,
        routes=base.routes,
        route_stops=(
            ImportRouteStop(route_ref="r1", stop_ref="s1", sequence=0),
            ImportRouteStop(route_ref="r1", stop_ref="s2", sequence=1),
        ),
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "invalid_sequence_ordering" in _issue_codes(result, "error")


def test_non_contiguous_sequence_is_a_warning_not_an_error():
    """The schema only requires sequence to be monotonic (see
    db/models/route_stop.py), not contiguous - a gap is a warning."""
    base = _minimal_valid_dataset()
    dataset = ImportDataset(
        agencies=base.agencies,
        stops=base.stops,
        routes=base.routes,
        route_stops=(
            ImportRouteStop(route_ref="r1", stop_ref="s1", sequence=1),
            ImportRouteStop(route_ref="r1", stop_ref="s2", sequence=5),
        ),
    )
    result = validate_dataset(dataset)
    assert result.is_valid
    assert "non_contiguous_sequence" in _issue_codes(result, "warning")


# ---------------------------------------------------------------------------
# Insufficient stops
# ---------------------------------------------------------------------------


def test_route_with_one_stop_is_an_error():
    dataset = ImportDataset(
        agencies=(ImportAgency(name="A"),),
        stops=(ImportStop(ref="s1", name="Only Stop", latitude=33.0, longitude=73.0),),
        routes=(ImportRoute(ref="r1", agency="A", short_name="T-1"),),
        route_stops=(ImportRouteStop(route_ref="r1", stop_ref="s1", sequence=1),),
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "insufficient_stops" in _issue_codes(result, "error")


def test_route_with_zero_stops_is_an_error():
    dataset = ImportDataset(
        agencies=(ImportAgency(name="A"),),
        stops=(),
        routes=(ImportRoute(ref="r1", agency="A", short_name="T-1"),),
        route_stops=(),
    )
    result = validate_dataset(dataset)
    assert not result.is_valid
    assert "insufficient_stops" in _issue_codes(result, "error")


def test_multiple_issues_are_all_reported_together():
    """A single validate_dataset call surfaces every problem at once,
    not just the first one - important so a caller doesn't have to fix
    and re-submit one error at a time."""
    dataset = ImportDataset(
        agencies=(ImportAgency(name="A"), ImportAgency(name="A")),
        stops=(ImportStop(ref="s1", name="Bad", latitude=999, longitude=73.0),),
        routes=(ImportRoute(ref="r1", agency="A", short_name="T-1"),),
        route_stops=(ImportRouteStop(route_ref="r1", stop_ref="missing", sequence=1),),
    )
    result = validate_dataset(dataset)
    codes = _issue_codes(result, "error")
    assert "duplicate_agency_name" in codes
    assert "invalid_coordinates" in codes
    assert "missing_stop_reference" in codes
    assert "insufficient_stops" in codes
