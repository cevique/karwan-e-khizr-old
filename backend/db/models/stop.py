"""
Stop - a physical location a vehicle can board/alight passengers at. May
serve multiple routes via RouteStop.

See README.md §11 "Transit Data Model" and §12 "Database Architecture".
Assumption A4 (README): `Station` (multi-platform clustering) is
deliberately not modeled separately from `Stop` at this stage.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.route_stop import RouteStop


class Stop(TimestampMixin, Base):
    """A physical transit stop location."""

    __tablename__ = "stops"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Stable external key from the canonical research dataset
    # (`docs/transit_data.json`), i.e. the dataset's `key`. Unlike `name`,
    # `ref` is unique per dataset stop even when two stops share a display
    # name (e.g. Red Line `faizabad` vs CDA feeder `cda_faizabad` - both
    # named "Faizabad"). `seeding.importer` matches on `ref` first, falling
    # back to `name` for legacy/admin imports that carry no ref. Nullable
    # (no NOT NULL) so rows created by the seed pipeline - which predates
    # this column - keep importing unchanged.
    ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Stored as `geography(Point, 4326)` (not plain lat/lon columns and not
    # the planar `geometry` type) because stops are the target of
    # proximity queries (`ST_DWithin`, e.g. README §11 Assumption A6's
    # 400m walking-connection radius) where `geography` gives correct
    # great-circle distances directly in meters without a manual
    # planar-projection step. `spatial_index=True` (GeoAlchemy2's default)
    # creates the GiST index the README's §12 "Notes" call for.
    #
    # Nullable: the canonical `transit_data.json` describes 122 stops, of
    # which ~105 have no coordinates yet (documented in
    # docs/DATA_GAPS.md). Those stops are imported with `location = NULL`
    # rather than being fabricated, and the routing graph + simulator
    # skip/guard them (see `routing/graph.py`, `simulation/trip_builder.py`).
    location: Mapped[str | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=True,
    )

    route_stops: Mapped[list["RouteStop"]] = relationship(
        back_populates="stop",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Stop(id={self.id!r}, name={self.name!r})"
