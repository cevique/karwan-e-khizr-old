"""
Shared SQLAlchemy declarative base.

All ORM models defined later in the application must inherit from `Base`.
`Base.metadata` is what Alembic's migration environment will import and use
for autogeneration once Alembic is configured (a later step) - so this file
intentionally stays minimal and defines no models of its own.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy ORM models."""

    pass
