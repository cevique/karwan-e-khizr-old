"""
FastAPI-facing dependency wiring for the simulation subsystem.

Kept in `api/`, not `simulation/` - mirrors `api/graph_state.py`'s own
rationale (see its docstring): `simulation` must stay importable and
testable without any FastAPI dependency, and everything here is
FastAPI-specific (`Depends`).
"""

from __future__ import annotations

from simulation.provider import (
    SimulatedVehicleLocationProvider,
    VehicleLocationProvider,
)
from simulation.service import SimulationService


def get_vehicle_location_provider() -> VehicleLocationProvider:
    """FastAPI dependency: a `VehicleLocationProvider`.

    A fresh, stateless `SimulatedVehicleLocationProvider` per request -
    it owns its own session lifecycle internally (see that class's
    docstring), so there's no per-request state to share or clean up
    here. Swapping in a real-GPS provider later means changing this one
    function, not any route handler that depends on it.
    """
    return SimulatedVehicleLocationProvider()


def get_simulation_service() -> SimulationService:
    """FastAPI dependency: a `SimulationService` for control operations."""
    return SimulationService()
