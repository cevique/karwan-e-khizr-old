"""
User - a registered account: a passenger by default, or (via the minimal
`role` field) a ticket validator/admin for operational purposes.

See README.md SS11/SS12 for the overall data model context. Users, auth,
fares, and ticketing are their own workstream, independent of the
foundational static transit-network models (Agency/Route/Stop/RouteStop) -
this module does not modify or import anything from those.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.ticket import Ticket

# Minimal, fixed role set for the hackathon MVP - deliberately no separate
# roles/permissions table (per the instruction not to overcomplicate
# roles). "passenger" is the only role self-registration can produce (see
# api/auth/router.py); "validator"/"admin" are operational roles assigned
# directly in the database/by an existing admin, not through public
# registration.
ROLE_PASSENGER = "passenger"
ROLE_VALIDATOR = "validator"
ROLE_ADMIN = "admin"
VALID_ROLES = (ROLE_PASSENGER, ROLE_VALIDATOR, ROLE_ADMIN)

# Roles allowed to call the ticket-validation endpoint (see
# api/tickets/router.py / users/dependencies.py's require_role).
VALIDATOR_ROLES = (ROLE_VALIDATOR, ROLE_ADMIN)


class User(TimestampMixin, Base):
    """A registered account."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Login identifier. Unique. Normalized (lowercased/stripped) at the
    # application layer before every read/write (see users/service.py) -
    # the column itself just stores whatever it's given.
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )

    # Never a plaintext password - always a bcrypt hash (see
    # users/security.py). Sized generously beyond bcrypt's fixed 60-char
    # output so a future hashing-algorithm change doesn't itself need a
    # column migration.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ROLE_PASSENGER, server_default=ROLE_PASSENGER
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Ticket.user_id",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"User(id={self.id!r}, email={self.email!r}, role={self.role!r})"
