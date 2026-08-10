"""
RouteStop - the ordered association of a Stop to a Route.

Modeled as an association *object* (its own table with a surrogate PK),
not a bare many-to-many table, because it already carries an attribute
beyond the two foreign keys (`sequence`), is a near-certain home for more
(`distance_along_route_m` now; per-stop timing/StopTime later per README
§11), and both existing terminology (README §11/§12) and the "ordered
sequence of stops" requirement call for a first-class row per (route,
stop, position) rather than an implicit ordering.

See README.md §11 "Transit Data Model" and §12 "Database Architecture".
"""

from __future__ import annotations

import decimal
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.route import Route
    from db.models.stop import Stop


class RouteStop(TimestampMixin, Base):
    """Ordered association of a Stop to a Route."""

    __tablename__ = "route_stops"
    __table_args__ = (
        # Explicit ordering field, per the requirement not to rely on row
        # insertion order - a route can't have two stops claiming the same
        # position in its sequence.
        UniqueConstraint(
            "route_id", "sequence", name="uq_route_stops_route_id_sequence"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    route_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stop_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stops.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # 1-based (or otherwise monotonic) position of this stop within the
    # route. The explicit ordering field called for instead of relying on
    # database row insertion order. Deliberately *not* also unique on
    # (route_id, stop_id): a loop route can legitimately serve the same
    # physical stop twice in one circuit.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    # Optional distance from the start of the route to this stop, in
    # meters. Nullable - not curated for every route yet, and deliberately
    # not derived/computed here; a future routing/import step can populate
    # it from `Route.path` once that geometry exists. Numeric (not float)
    # to avoid floating-point drift for a value that may feed fare-tier or
    # ETA calculations later.
    distance_along_route_m: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )

    route: Mapped["Route"] = relationship(back_populates="route_stops")
    stop: Mapped["Stop"] = relationship(back_populates="route_stops")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"RouteStop(route_id={self.route_id!r}, stop_id={self.stop_id!r}, "
            f"sequence={self.sequence!r})"
        )
