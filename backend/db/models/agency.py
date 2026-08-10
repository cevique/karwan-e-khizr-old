"""
Agency - a transit operator/network (e.g. "CDA Buses", "Metro").

See README.md §11 "Transit Data Model": needed because the app is
explicitly multi-network, and every `Route` belongs to exactly one Agency.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base
from db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from db.models.route import Route


class Agency(TimestampMixin, Base):
    """A transit operator/network that owns zero or more Routes."""

    __tablename__ = "agencies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Operator/network display name, e.g. "CDA Buses", "Metro". Unique so the
    # same operator can't be curated into the dataset twice by accident.
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    # Free-form classification (e.g. "brt", "feeder", "metro"). Nullable and
    # unconstrained on purpose - the hackathon dataset doesn't need a fixed
    # enum of network types yet, and adding one later is a migration on this
    # single column, not a schema redesign.
    network_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    routes: Mapped[list["Route"]] = relationship(
        back_populates="agency",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"Agency(id={self.id!r}, name={self.name!r})"
