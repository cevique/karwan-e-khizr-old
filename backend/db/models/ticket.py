"""
Ticket - a purchased/issued transit ticket for one passenger.

Deliberately does NOT persist a `Journey` (see routing/journey.py) - a
Journey is a computed routing result, not a database entity, per this
workstream's explicit instructions. Only the small summary needed to
identify the purchased trip and show a receipt is stored here; the
authoritative leg-by-leg detail lives wherever the client cached the
original `POST /api/transit/journeys/search` response that led to this
purchase.

See `ticketing.tickets.service` for the ticket lifecycle (create /
validate / revoke / expire) and `ticketing.tickets.qr` for the QR payload
format.
"""

from __future__ import annotations

import decimal
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.user import User

# Ticket lifecycle states. Plain strings (not a DB enum type), consistent
# with how other unconstrained-but-fixed-ish string fields are modeled
# elsewhere in this codebase (e.g. Agency.network_type) - adding a state
# later is a code change, not a migration.
STATUS_ACTIVE = "active"  # purchased, not yet validated/consumed
STATUS_USED = "used"  # validated/consumed exactly once
STATUS_EXPIRED = "expired"  # past valid_until, never validated
STATUS_REVOKED = "revoked"  # cancelled by the owner or an admin/validator
VALID_STATUSES = (STATUS_ACTIVE, STATUS_USED, STATUS_EXPIRED, STATUS_REVOKED)


class Ticket(TimestampMixin, Base):
    """A purchased ticket for a single origin-to-destination journey."""

    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Short, human-typeable identifier distinct from `id` (e.g. for a
    # receipt, a support call, or a manual fallback lookup) - see
    # ticketing.tickets.service for how it's generated. NOT used for QR
    # verification; the QR payload authenticates `id`, not this.
    ticket_code: Mapped[str] = mapped_column(
        String(12), nullable=False, unique=True, index=True
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_ACTIVE, server_default=STATUS_ACTIVE
    )

    fare_amount: Mapped[decimal.Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PKR")

    # Minimal journey summary - enough to render a receipt and audit the
    # fare that was charged, not a duplicate of the routed Journey.
    # Coordinates are plain floats (not PostGIS geography): nothing here
    # does spatial querying over past tickets - this is a persisted
    # receipt, not routing input.
    objective: Mapped[str] = mapped_column(String(30), nullable=False)
    origin_lat: Mapped[float] = mapped_column(nullable=False)
    origin_lon: Mapped[float] = mapped_column(nullable=False)
    destination_lat: Mapped[float] = mapped_column(nullable=False)
    destination_lon: Mapped[float] = mapped_column(nullable=False)
    ride_leg_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transfer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_duration_s: Mapped[float | None] = mapped_column(nullable=True)
    total_walk_m: Mapped[float | None] = mapped_column(nullable=True)
    # Ordered list of route short_names ridden, e.g. ["FR-03", "M-1"] -
    # display-only, for a receipt; not consulted by validation.
    route_summary: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="tickets", foreign_keys=[user_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Ticket(id={self.id!r}, ticket_code={self.ticket_code!r}, status={self.status!r})"
