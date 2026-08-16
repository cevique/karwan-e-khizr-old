"""make stops.location nullable

The canonical docs/transit_data.json dataset (Phase 1 import, plan.md
section B) describes 122 stops, ~105 of which have no coordinates yet
(documented in docs/DATA_GAPS.md). Those stops must be importable as
Stop rows with `location = NULL` rather than being fabricated - the
coordinate values will come later from the geospatial-enrichment pass
(plan.md section C). This migration relaxes the foundational
`nullable=False` constraint on `stops.location`.

Hand-written, matching db/models/stop.py (Stop.location is now
`Mapped[str | None]`). Chained linearly on the current head
(4795c429e65f); it does not touch any table other than `stops`, so it
cannot conflict with the realtime/users workstreams.

Revision ID: a1b2c3d4e5f6
Revises: 4795c429e65f
Create Date: 2026-08-17 00:00:00.000000

"""

from typing import Sequence, Union

import geoalchemy2
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "4795c429e65f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "stops",
        "location",
        existing_type=geoalchemy2.types.Geography(
            geometry_type="POINT",
            srid=4326,
            spatial_index=False,
            from_text="ST_GeogFromText",
            name="geography",
        ),
        nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "stops",
        "location",
        existing_type=geoalchemy2.types.Geography(
            geometry_type="POINT",
            srid=4326,
            spatial_index=False,
            from_text="ST_GeogFromText",
            name="geography",
        ),
        nullable=False,
    )