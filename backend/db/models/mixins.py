"""
Shared mixins for ORM models.

Kept separate from `db/base.py` because `Base` itself intentionally stays a
plain `DeclarativeBase` with no columns of its own (see its docstring) -
this mixin is opt-in per model instead.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds timezone-aware `created_at` / `updated_at` columns.

    Both are server-side defaults (`func.now()`), not application-side, so
    the value is correct regardless of which process/clock inserts or
    updates the row.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
