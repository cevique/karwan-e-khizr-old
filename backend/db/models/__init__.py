"""
ORM model package.

Importing this package registers every model class with `db.base.Base`'s
shared declarative registry/metadata, which is what both Alembic
autogenerate (see `alembic/env.py`) and SQLAlchemy's relationship string
resolution (e.g. `Mapped["Route"]`) depend on. Import this package - not
individual model modules - wherever "all models" need to be known.

Only the foundational static transit-network models are implemented at
this stage (Agency, Route, Stop, RouteStop). Vehicles/live positions,
ticketing, payments, users, and government-integration models are later,
separate steps - see README.md §11 for the full target data model and
which parts of it are deliberately not built yet.
"""

from db.models.agency import Agency
from db.models.route import Route
from db.models.route_stop import RouteStop
from db.models.stop import Stop

__all__ = ["Agency", "Route", "RouteStop", "Stop"]
