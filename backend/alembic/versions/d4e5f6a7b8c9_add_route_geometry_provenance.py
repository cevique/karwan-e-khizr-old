"""add route geometry provenance

Phase 3 of plan.md (section D / section K, Migration 2): tracks where each
`Route.path` polyline came from and how much to trust it, mirroring Phase
2's `stops.coordinate_source`/`coordinate_confidence` columns
(c3d4e5f6a7b8) for the same reason - `path` alone can't distinguish "no
geometry generated yet" from "geometry generation was attempted and
failed" from "this is a real, road-following polyline".

Hand-written, matching db/models/route.py (`geometry_source` and
`geometry_confidence` are both `Mapped[str | None]`). Chained linearly on
the current head (c3d4e5f6a7b8); it only touches `routes`, so it cannot
conflict with other workstreams.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("routes", sa.Column("geometry_source", sa.String(length=50), nullable=True))
    op.add_column(
        "routes", sa.Column("geometry_confidence", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("routes", "geometry_confidence")
    op.drop_column("routes", "geometry_source")
