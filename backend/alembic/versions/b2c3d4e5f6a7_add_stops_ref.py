"""add stops.ref

The canonical docs/transit_data.json dataset (Phase 1 import, plan.md
section B) contains four pairs of DISTINCT stops that share a display
`name` (e.g. Red Line `faizabad` vs CDA feeder `cda_faizabad`, both named
"Faizabad"). `seeding.importer`'s name-based get-or-create therefore
collapsed them into single rows, corrupting the routing graph (both
routes would share one stop node).

This migration adds a nullable `ref` column holding the dataset's stable
`key`, which `seeding.importer` uses as the real identity (falling back
to `name` only when no ref is present - i.e. legacy/admin data).

Hand-written, matching db/models/stop.py (Stop.ref is
`Mapped[str | None]`). Chained linearly on the current head
(a1b2c3d4e5f6); it does not touch any table other than `stops`, so it
cannot conflict with the realtime/users workstreams.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-17 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("stops", sa.Column("ref", sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("stops", "ref")