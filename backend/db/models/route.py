"""
Route - a named/numbered transit service (e.g. "FR-03") belonging to one
Agency, with a display color and an optional path geometry for map
rendering.

See README.md §11 "Transit Data Model" and §12 "Database Architecture".
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.agency import Agency
    from db.models.route_stop import RouteStop


class Route(TimestampMixin, Base):
    """A single transit route/service belonging to one Agency."""

    __tablename__ = "routes"
    __table_args__ = (
        # A given operator shouldn't curate the same route code twice.
        # Different agencies re-using the same short_name (unlikely, but not
        # impossible for e.g. "R1") is explicitly allowed.
        UniqueConstraint(
            "agency_id", "short_name", name="uq_routes_agency_id_short_name"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Short code shown on the map/vehicle, e.g. "FR-03".
    short_name: Mapped[str] = mapped_column(String(50), nullable=False)
    # Optional full descriptive name, e.g. "Faizabad - Rawat".
    long_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional display color as a hex triplet, e.g. "#E53935".
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)

    # Route geometry for map display (a polyline of the road/corridor the
    # route follows). Stored as `geometry` (not `geography`) with SRID 4326
    # (WGS84) per the README ERD's `path` field - it's used for rendering
    # and length/measurement math, not proximity search, so the planar
    # `geometry` type is the right PostGIS type here (Stop.location below
    # uses `geography` instead, since that column *is* used for proximity
    # search). Nullable because route geometry may not be curated yet at
    # the time a Route row is created.
    path: Mapped[str | None] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4326),
        nullable=True,
    )

    agency: Mapped["Agency"] = relationship(back_populates="routes")

    # Ordered via the association object's `sequence` column (not row
    # insertion order) - see RouteStop.
    route_stops: Mapped[list["RouteStop"]] = relationship(
        back_populates="route",
        cascade="all, delete-orphan",
        order_by="RouteStop.sequence",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Route(id={self.id!r}, short_name={self.short_name!r})"
