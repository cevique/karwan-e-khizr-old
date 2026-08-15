"""
Realtime transit simulation subsystem.

Simulates buses moving through the existing static transit network
(`Route` / `RouteStop` / `Stop`) and exposes their current positions/state
through a small, FastAPI/SQLAlchemy-independent interface
(`simulation.provider.VehicleLocationProvider`), so a future real-GPS
provider can be substituted without any caller-side change.

Module map:

- `simulation.geo` - dependency-free WGS84 point + straight-line distance
  and interpolation helpers. Deliberately NOT imported from
  `backend/routing/` (which has its own, separate copy) - this package
  must stay decoupled from the routing engine (see the module docstrings
  in `simulation.engine`/`simulation.provider` for why).
- `simulation.timing` - the "minimum necessary assumption" for
  schedule-based movement when no real timetable exists: a constant
  assumed speed/dwell time and the pure function that turns a route's
  stop sequence into `StopTime` arrival/departure offsets from it.
- `simulation.engine` - the deterministic core: given a `TripSchedule`
  (pure data, no I/O) and an elapsed-seconds value, computes exactly one
  simulated position. No randomness, no wall-clock reads - same inputs
  always produce the same output.
- `simulation.trip_builder` - the minimum-viable way to get a demo-able
  `Trip` (+ its `StopTime`s) for a `Route`, without depending on any
  dedicated GTFS-style import/seeding module.
- `simulation.provider` - `VehicleLocationProvider`, the replaceable
  interface, plus `SimulatedVehicleLocationProvider`, the DB-backed
  implementation that turns "now" + a `Trip`'s schedule into a live
  position via `simulation.engine`.
- `simulation.service` - `SimulationService`: the control-plane
  (start/stop a Trip, persist a position snapshot, inspect state),
  usable directly from Python (no HTTP required) as well as from the
  dev-only control router under `api/transit/realtime/`.
"""
