"""
ORM model package.

Importing this package registers every model class with `db.base.Base`'s
shared declarative registry/metadata, which is what both Alembic
autogenerate (see `alembic/env.py`) and SQLAlchemy's relationship string
resolution (e.g. `Mapped["Route"]`) depend on. Import this package - not
individual model modules - wherever "all models" need to be known.

All models implemented so far are registered here:

- Foundational static transit-network models: Agency, Route, Stop,
  RouteStop.
- Realtime/simulation models (Claude A workstream): Vehicle, Trip,
  StopTime, VehiclePosition.
- Users/fares/ticketing models (Claude B workstream): User, FareRule,
  Ticket.

Government-integration models are a later, separate step - see
README.md SS11 for the full target data model and which parts of it are
deliberately not built yet.

INTEGRATION NOTE: this file is shared across parallel workstreams. Claude
A's copy added Vehicle/Trip/StopTime/VehiclePosition; Claude B's
workstream deliberately did NOT modify this file (out of its own
ownership bounds - see db/models/user.py's module docstring), so User/
FareRule/Ticket were added here at integration time, at the end of the
import list, after the realtime/simulation models. Import order here has
no runtime significance (each model module is independent / has no
import-time dependency on another model module's import having already
happened) - it is kept in "workstream arrival order" purely for
readability of this file's history.
"""

from db.models.agency import Agency
from db.models.route import Route
from db.models.route_stop import RouteStop
from db.models.stop import Stop
from db.models.stop_time import StopTime
from db.models.trip import Trip
from db.models.vehicle import Vehicle
from db.models.vehicle_position import VehiclePosition
from db.models.user import User
from db.models.fare import FareRule
from db.models.ticket import Ticket

__all__ = [
    "Agency",
    "Route",
    "RouteStop",
    "Stop",
    "StopTime",
    "Trip",
    "Vehicle",
    "VehiclePosition",
    "User",
    "FareRule",
    "Ticket",
]
