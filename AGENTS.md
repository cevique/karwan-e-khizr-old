# Karwan-e-Khizr — Project Instructions for AI Agents

## Project Overview

Karwan-e-Khizr is a public-transit journey-planning application for the Islamabad/Rawalpindi twin cities in Pakistan. The repository contains a FastAPI + SQLAlchemy 2.x async + PostgreSQL/PostGIS backend. The frontend will be developed separately by another teammate.

## Repository Structure

```
karwan-e-khizr/
├── backend/
│   ├── main.py                    # FastAPI entrypoint (lifespan builds routing graph)
│   ├── requirements.txt
│   ├── docker-compose.yml         # PostgreSQL/PostGIS container
│   ├── alembic.ini                # Migration config
│   ├── alembic/versions/          # 3 existing migrations
│   ├── api/                       # FastAPI routers (HTTP endpoints)
│   │   ├── router.py              # Top-level API router aggregator
│   │   ├── health.py              # GET /health
│   │   ├── graph_state.py         # Routing graph lifecycle wiring
│   │   ├── transit/               # Transit data, journey, realtime APIs
│   │   ├── auth/                  # Authentication endpoints
│   │   ├── users/                 # User profile endpoints
│   │   ├── fares/                 # Fare quoting endpoints
│   │   ├── tickets/               # Ticket purchase/validate endpoints
│   │   ├── admin/                 # Destructive admin/seed/import endpoints
│   │   └── dev/                   # Read-only dev inspection endpoints
│   ├── routing/                   # Route planning engine (pure Python)
│   ├── simulation/                # Vehicle position simulation engine
│   ├── db/                        # SQLAlchemy ORM + session infrastructure
│   │   └── models/                # 11 ORM models
│   ├── core/                      # Application settings
│   ├── users/                     # User business logic + auth dependencies
│   ├── ticketing/                 # Fare calculation + ticket lifecycle
│   ├── seeding/                   # Seed data + import pipeline
│   ├── data/                      # Deterministic demo seed data
│   ├── scripts/                   # CLI scripts
│   ├── tests/                     # 406 passing tests (31 test files)
│   └── docs/                      # Research documents (source of truth)
```

## Tech Stack

- **Framework**: FastAPI (async)
- **ORM**: SQLAlchemy 2.x (async, asyncpg driver)
- **Database**: PostgreSQL 16 + PostGIS (via Docker)
- **Migrations**: Alembic
- **Auth**: bcrypt + JWT (PyJWT)
- **Testing**: pytest + pytest-asyncio + httpx
- **Geo**: GeoAlchemy2 (PostGIS), no Shapely dependency

## Working Directory

All backend work happens in `backend/`. Run commands from there unless otherwise specified.

## Running the Backend

```bash
# From backend/
uvicorn main:app --reload

# Database via Docker
docker-compose up -d

# Database URL
postgresql+asyncpg://postgres:postgres@localhost:5432/karwan_e_khizr
```

## Running Tests

```bash
# From backend/
pytest

# Current baseline: 406 tests, 0 failures
```

## Key Architecture Principles

1. **Provider/Protocol pattern**: `VehicleLocationProvider`, `WalkingProvider`, and `PaymentProvider` are Protocol interfaces. Swappable implementations.

2. **Immutable graph**: `TransitGraph` uses `MappingProxyType` and tuples. Rebuilt atomically at startup.

3. **Separation of concerns**: `routing/` has zero FastAPI/SQLAlchemy imports. `simulation/` has zero FastAPI imports. `api/` is the only layer with both.

4. **Schema separation**: ORM models are never returned from endpoints. API schemas (`api/transit/schemas.py`) are always used for responses.

5. **Transaction boundaries**: Service functions take `AsyncSession` and flush but never commit — the API route handler commits.

6. **Deterministic seeding**: All seed data uses `uuid.uuid5` for IDs, making seed/reset operations safe and repeatable.

7. **No fabricated data**: Never invent coordinates, stop names, timetables, or route geometry. All data must have a source.

8. **Provenance tracking**: All enriched data (geocoded coordinates, OSRM geometry) must carry source and confidence metadata.

## Current Data Model

### Static Transit Models
- **Agency** (`agencies`): id (UUID), name (unique), network_type
- **Route** (`routes`): id, agency_id (FK), short_name, long_name, color, path (PostGIS LINESTRING, currently NULL)
- **Stop** (`stops`): id, name, location (PostGIS geography POINT 4326)
- **RouteStop** (`route_stops`): id, route_id (FK), stop_id (FK), sequence, distance_along_route_m (nullable)

### Realtime/Simulation Models
- **Vehicle** (`vehicles`): id, fleet_number (unique), is_active, notes
- **Trip** (`trips`): id, route_id (FK), vehicle_id (FK nullable), status, scheduled_start_time
- **StopTime** (`stop_times`): id, trip_id (FK), stop_id (FK), sequence, arrival_offset_s, departure_offset_s
- **VehiclePosition** (`vehicle_positions`): id, vehicle_id (FK), trip_id (FK nullable), latitude, longitude, recorded_at, current_stop_id, next_stop_id, status

### Users/Fares/Ticketing Models
- **User** (`users`): id, name, email (unique), password_hash, role, is_active
- **FareRule** (`fare_rules`): id, name (unique), base_fare, per_leg_fare, currency, is_active
- **Ticket** (`tickets`): id, ticket_code (unique), user_id (FK), status, fare_amount, journey summary fields, validity timestamps

## Existing API Endpoints

### Transit Static (`/api/transit`)
- `GET /api/transit/agencies` — list agencies
- `GET /api/transit/routes` — list routes (optional agency_id filter)
- `GET /api/transit/routes/{route_id}` — route detail with ordered stops
- `GET /api/transit/stops` — list stops (optional nearby search with lat/lon/radius)
- `GET /api/transit/stops/{stop_id}` — single stop detail

### Journey Search (`/api/transit/journeys`)
- `POST /api/transit/journeys/search` — find optimal journey (fastest/fewest_transfers/least_walking)

### Realtime Vehicle Positions (`/api/transit/realtime`)
- `GET /api/transit/realtime/vehicles` — all active vehicle positions
- `GET /api/transit/realtime/vehicles/{vehicle_id}` — single vehicle position
- `GET /api/transit/realtime/routes/{route_id}/vehicles` — vehicles on a route
- `GET /api/transit/realtime/trips/{trip_id}/vehicles` — vehicle on a trip

### Simulation Control (`/api/transit/realtime/simulation`, unauthenticated)
- `POST /api/transit/realtime/simulation/trips/{trip_id}/start`
- `POST /api/transit/realtime/simulation/trips/{trip_id}/stop`
- `POST /api/transit/realtime/simulation/routes/{route_id}/demo-trip`
- `POST /api/transit/realtime/simulation/vehicles/{vehicle_id}/record-position`
- `GET /api/transit/realtime/simulation/state`

### Auth/Users/Fares/Tickets
- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`
- `GET /api/users/me`
- `POST /api/fares/quote`
- `POST /api/tickets`, `GET /api/tickets`, `POST /api/tickets/validate`, etc.

### Admin (`/api/admin`, requires admin role)
- `POST /api/admin/seed`, `POST /api/admin/seed/reset`
- `POST /api/admin/import`, `POST /api/admin/import/csv`
- `POST /api/admin/graph/rebuild`

### Dev (`/api/dev`, read-only)
- `GET /api/dev/status`, `POST /api/dev/validate`, `POST /api/dev/validate/seed`

## Research Documents (Source of Truth)

Located in `backend/docs/`:

- **TRANSIT_RESEARCH.md** — Master research document with all route/stop/timetable information
- **transit_data.json** — Canonical machine-readable dataset (28 routes, 97 stops, 4 timetable patterns)
- **SOURCES.md** — All data sources and their reliability
- **DATA_GAPS.md** — Confirmed missing data and conflicts
- **MAP_AND_REALTIME_RECOMMENDATIONS.md** — Architecture recommendations for map and realtime
- **SIMULATION_DATA_SPEC.md** — Specification for how research data maps to the database

### Key Research Facts

**Researched timetable data (official CDA PDFs):**
- FR-01: 26 stops, 16 trips/day, 60-min headway
- FR-04: 25 stops, 97 trips/day, 10-min headway
- FR-07: 23 stops, 97 trips/day, 10-min headway
- FR-14: 18 stops, 65 trips/day, 15-min headway

**No timetable data exists for:** Red Line, Orange Line, Blue Line, Green Line, or 18 other CDA feeder routes.

**No route geometry exists for any route.** All `Route.path` values are NULL.

**Stop coordinates:** 17 stops have APPROXIMATE coordinates from seed dataset. ~80 stops have null coordinates.

## Implementation Plan

See `backend/plan.md` for the full Phase 2 implementation plan with 6 sequential phases:
1. Transit Data Import
2. Geospatial Enrichment (Nominatim)
3. Route Geometry (OSRM)
4. Enhanced Realtime API
5. Trip Generation Admin
6. Frontend Integration Readiness

## Constraints

1. Do not rewrite working subsystems unnecessarily.
2. Do not fabricate transit data.
3. Do not fabricate stop coordinates.
4. Do not fabricate route geometry.
5. Preserve source provenance.
6. Prefer existing architecture over introducing duplicate systems.
7. Preserve Alembic migration correctness.
8. Preserve API compatibility unless a change is justified.
9. Keep simulator and real-realtime providers behind abstractions.
10. Keep the frontend/backend boundary clean.
11. Preserve the 406-test baseline.
12. Do not modify code while in planning mode without approval.
