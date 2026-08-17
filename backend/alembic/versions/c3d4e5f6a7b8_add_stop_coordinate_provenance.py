"""add stop coordinate provenance

Phase 2 of plan.md (section C / section K, Migration 1): tracks where each
`Stop.location` value came from and how much to trust it, so the ~105
stops the canonical docs/transit_data.json dataset leaves without
coordinates (Phase 1) can be enriched via `scripts/geocode_stops.py`
without losing the distinction between a seeded coordinate, a geocoded
one, and "we tried and found nothing".

Hand-written, matching db/models/stop.py (`coordinate_source` and
`coordinate_confidence` are both `Mapped[str | None]`). Chained linearly
on the current head (b2c3d4e5f6a7); it only touches `stops`, so it
cannot conflict with other workstreams.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("stops", sa.Column("coordinate_source", sa.String(length=50), nullable=True))
    op.add_column(
        "stops", sa.Column("coordinate_confidence", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("stops", "coordinate_confidence")
    op.drop_column("stops", "coordinate_source")
