"""
ORM model package.

Importing this package registers every model class with `db.base.Base`'s
shared declarative registry/metadata, which is what both Alembic
autogenerate (see `alembic/env.py`) and SQLAlchemy's relationship string
resolution (e.g. `Mapped["Route"]`) depend on. Import this package - not
individual model modules - wherever "all models" need to be known.

Foundational static transit-network models (Agency, Route, Stop,
RouteStop) plus the realtime/simulation models (Vehicle, Trip, StopTime,
VehiclePosition) are implemented at this stage. Ticketing, payments,
users, and government-integration models are later, separate steps - see
README.md §11 for the full target data model and which parts of it are
deliberately not built yet.

NOTE: this file is shared across parallel workstreams (each adding their
own models here) - expect it to need reconciling at integration time if
more than one workstream touches it concurrently.
"""

from db.models.agency import Agency
from db.models.route import Route
from db.models.route_stop import RouteStop
from db.models.stop import Stop
from db.models.stop_time import StopTime
from db.models.trip import Trip
from db.models.vehicle import Vehicle
from db.models.vehicle_position import VehiclePosition

__all__ = [
    "Agency",
    "Route",
    "RouteStop",
    "Stop",
    "StopTime",
    "Trip",
    "Vehicle",
    "VehiclePosition",
]
