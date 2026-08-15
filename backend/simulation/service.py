"""
`SimulationService`: the control-plane for the simulator - start/stop a
Trip, persist a position snapshot, inspect current state.

Deliberately a plain Python class over `AsyncSession`, with no FastAPI
dependency, so it's usable directly from a script or a test, not only
from HTTP - see the task's "the simulator must also be usable
programmatically without HTTP" requirement. `api/transit/realtime/
control_router.py` is a thin HTTP wrapper around this class, not a
second implementation of its logic.

This is intentionally the ONLY place that mutates `Trip.status`/
`Trip.vehicle_id` or writes `VehiclePosition` rows - `simulation.provider`
(the read path) never mutates anything.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Trip, Vehicle, VehiclePosition
from simulation.engine import SimulatedPosition, compute_position_at
from simulation.provider import Clock, default_clock, fetch_trips
from simulation.trip_builder import load_trip_schedule


class TripNotFoundError(ValueError):
    """Raised when a `SimulationService` control operation names a
    `trip_id` that doesn't exist."""


class VehicleNotFoundError(ValueError):
    """Raised when a `SimulationService` control operation names a
    `vehicle_id` that doesn't exist."""


class SimulationService:
    """Control-plane operations for the simulator.

    Every method here takes an explicit `AsyncSession` (unlike
    `simulation.provider.SimulatedVehicleLocationProvider`, which owns its
    own session lifecycle) because control operations are naturally
    request/script-scoped, single-shot mutations that the caller commits
    - matching the convention `simulation.trip_builder.build_trip_for_route`
    already follows (flush, not commit; the caller decides the
    transaction boundary).
    """

    def __init__(self, *, clock: Clock = default_clock) -> None:
        self._clock = clock

    async def start_trip(
        self,
        session: AsyncSession,
        *,
        trip_id: uuid.UUID,
        vehicle_id: uuid.UUID,
        start_time: datetime | None = None,
    ) -> Trip:
        """Assign `vehicle_id` to `trip_id` and mark it `"active"`,
        starting its elapsed-time clock at `start_time` (defaulting to
        now).

        Raises `TripNotFoundError`/`VehicleNotFoundError` if either id
        doesn't exist. Does not check the trip has any `StopTime`s - a
        trip with no schedule simply won't produce a position (see
        `simulation.trip_builder.load_trip_schedule`), which is treated
        as "no position available" rather than an error at start time.
        """
        trip = await session.get(Trip, trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip {trip_id} does not exist")
        vehicle = await session.get(Vehicle, vehicle_id)
        if vehicle is None:
            raise VehicleNotFoundError(f"Vehicle {vehicle_id} does not exist")

        trip.vehicle_id = vehicle_id
        trip.status = "active"
        trip.scheduled_start_time = start_time or self._clock()
        await session.flush()
        return trip

    async def stop_trip(
        self,
        session: AsyncSession,
        *,
        trip_id: uuid.UUID,
        completed: bool = False,
    ) -> Trip:
        """Stop a running trip: `"completed"` if it finished normally,
        `"cancelled"` (the default) if it's being stopped early via
        simulation control.

        Raises `TripNotFoundError` if `trip_id` doesn't exist.
        """
        trip = await session.get(Trip, trip_id)
        if trip is None:
            raise TripNotFoundError(f"Trip {trip_id} does not exist")

        trip.status = "completed" if completed else "cancelled"
        await session.flush()
        return trip

    async def record_position(
        self, session: AsyncSession, *, vehicle_id: uuid.UUID
    ) -> VehiclePosition | None:
        """Compute `vehicle_id`'s current simulated position and persist
        it as a new `VehiclePosition` row - the DB-writing counterpart to
        `simulation.provider.VehicleLocationProvider.get_vehicle_position`,
        for whichever consumer wants a durable history/trail rather than
        only "right now" (see `db/models/vehicle_position.py`'s
        docstring).

        Returns `None` (and writes nothing) if the vehicle has no active
        trip with a computable position right now.
        """
        now = self._clock()
        trips = await fetch_trips(session, vehicle_id=vehicle_id)
        if not trips:
            return None

        trip = trips[0]
        schedule = await load_trip_schedule(session, trip.id)
        if schedule is None:
            return None

        elapsed_s = (now - trip.scheduled_start_time).total_seconds()
        simulated = compute_position_at(
            schedule, elapsed_s, vehicle_id=vehicle_id, as_of=now
        )

        position = VehiclePosition(
            vehicle_id=vehicle_id,
            trip_id=trip.id,
            latitude=simulated.latitude,
            longitude=simulated.longitude,
            recorded_at=now,
            current_stop_id=simulated.current_stop_id,
            next_stop_id=simulated.next_stop_id,
            status=simulated.status,
        )
        session.add(position)
        await session.flush()
        return position

    async def record_all_active_positions(
        self, session: AsyncSession
    ) -> list[VehiclePosition]:
        """Convenience "tick": persist a `VehiclePosition` snapshot for
        every currently-active vehicle. Intended for a manual dev/demo
        control action (see `api/transit/realtime/control_router.py`),
        not an automatic background loop - this workstream does not wire
        any periodic scheduling into `main.py`'s lifespan (out of
        ownership bounds; see this module's docstring)."""
        now = self._clock()
        trips = await fetch_trips(session)
        recorded: list[VehiclePosition] = []
        for trip in trips:
            if trip.vehicle_id is None:
                continue
            schedule = await load_trip_schedule(session, trip.id)
            if schedule is None:
                continue
            elapsed_s = (now - trip.scheduled_start_time).total_seconds()
            simulated: SimulatedPosition = compute_position_at(
                schedule, elapsed_s, vehicle_id=trip.vehicle_id, as_of=now
            )
            position = VehiclePosition(
                vehicle_id=trip.vehicle_id,
                trip_id=trip.id,
                latitude=simulated.latitude,
                longitude=simulated.longitude,
                recorded_at=now,
                current_stop_id=simulated.current_stop_id,
                next_stop_id=simulated.next_stop_id,
                status=simulated.status,
            )
            session.add(position)
            recorded.append(position)
        await session.flush()
        return recorded

    async def active_trip_ids(self, session: AsyncSession) -> list[uuid.UUID]:
        """Inspection helper: ids of every currently-`"active"` trip with
        a vehicle assigned."""
        trips = await fetch_trips(session)
        return [trip.id for trip in trips]
