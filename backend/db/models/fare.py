"""
FareRule - a named, configurable fare policy.

Deliberately NOT a full fare engine: the hackathon dataset has no reliable
per-route distance data (`RouteStop.distance_along_route_m` is optional
and largely uncurated - see db/models/route_stop.py) and a `JourneyRead`
response only exposes walking distance, not ride distance (see
api/transit/journey_schemas.py), so a true distance-based fare isn't
computable from what actually exists yet. Instead, fares are a
configurable flat amount per ride leg (boarding), stored as data here
rather than a hardcoded constant, so the amount can change without a code
change. See `ticketing.fares.service` for the exact formula and its
fallback when no row exists yet.
"""

from __future__ import annotations

import decimal
import uuid

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base
from db.models.mixins import TimestampMixin


class FareRule(TimestampMixin, Base):
    """A named, configurable fare policy.

    At most one row is expected to be `is_active` at a time. This is
    enforced by application logic (`ticketing.fares.service`), not a
    database constraint - a hackathon-appropriate simplification; a
    partial unique index would be the natural next step if this evolves
    past the MVP.
    """

    __tablename__ = "fare_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    # Flat amount charged once a journey involves at least one ride leg,
    # plus `per_leg_fare` for each *additional* ride leg beyond the first
    # (i.e. each transfer onto another route). See
    # ticketing.fares.service.calculate_fare's docstring for the full
    # formula. A journey with zero ride legs (pure walking) is always
    # free, regardless of this rule.
    base_fare: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    per_leg_fare: Mapped[decimal.Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=decimal.Decimal("0")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PKR")

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"FareRule(name={self.name!r}, base_fare={self.base_fare!r})"
