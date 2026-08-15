"""
Realtime vehicle-position API: "where is this vehicle right now" (as
opposed to `api/transit/vehicles/`, which answers "what vehicles/trips
exist").

Two routers live here, kept deliberately separate:

- `router.router` (prefix `/transit/realtime`) - public, read-only
  position endpoints. Safe to always mount.
- `control_router.router` (prefix `/transit/realtime/simulation`) -
  dev/demo simulation control (start/stop a trip, seed a demo trip from a
  route, force a position snapshot). NOT safe to expose unconditionally
  in a real deployment - see that module's own docstring. Isolated here
  precisely so the integrator can choose whether/when to mount it.

INTEGRATION NOTE (for whoever reconciles the three workstreams):
this workstream does not modify `api/router.py` (out of ownership
bounds). To wire these routers into the app, add to `api/router.py`:

    from api.transit.realtime.router import router as realtime_router
    from api.transit.realtime.control_router import (
        router as realtime_simulation_control_router,
    )
    from api.transit.vehicles.router import router as vehicles_router

    api_router.include_router(vehicles_router)
    api_router.include_router(realtime_router)
    # Optional / dev-only - see control_router.py's docstring:
    api_router.include_router(realtime_simulation_control_router)
"""
