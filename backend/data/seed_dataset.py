"""
The deterministic development/demo dataset: agencies, stops, and routes
loosely modeled on the real Islamabad Metrobus (blue line) and Rawalpindi
Metrobus (red line) BRT corridors plus two short feeder routes, all
expressed as plain, immutable Python data (no I/O, no database, no
randomness) so it can be imported and read anywhere without side effects.

Why these particular stops/routes (see README.md at the top of this
package's parent directory, `backend/data/README.md`, for the fuller
write-up):

- Two BRT-style routes sharing a real interchange stop ("Faizabad") give
  a same-stop transfer between two different agencies.
- A feeder route ("F-2") includes "Melody" - a stop already used by the
  blue line - giving a second same-stop transfer, this time between a
  feeder and a trunk route.
- A second feeder route ("F-1") ends at "Bank Road", which is close to
  but NOT the same stop as "Saddar" (on the red line). The two are within
  the routing graph's walking radius (see `routing.graph.WALKING_RADIUS_M`,
  400m) but far enough apart to not just be the same physical location -
  this exercises a walking-edge transfer between routes/agencies that
  don't share a stop, which matters for `least_walking` vs `fastest` vs
  `fewest_transfers` search objectives giving genuinely different answers.
- Coordinates are hand-picked to be *geographically plausible* (real
  place names, correct rough relative positions, monotonic-ish paths
  along each corridor) but are NOT surveyed/GTFS-grade positions - see
  the Limitations section of `backend/data/README.md`.

Every entity below has a short, stable `key` (never persisted, never
shown to a client) that `seeding.seed` uses to derive a deterministic
UUID via `uuid.uuid5(SEED_NAMESPACE, ...)`. Two consequences of that:

1. Re-running the seed against the same (or any) empty database always
   produces the exact same row IDs - "deterministic" per the task's
   requirement, and convenient for demos/screenshots that reference an
   ID directly.
2. `seeding.seed`'s reset/replace operations can delete *exactly* the
   rows this dataset owns (by ID) without ever touching unrelated data -
   see that module's docstring.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

# Fixed, arbitrary-but-stable namespace for every ID derived from this
# dataset. `uuid.uuid5` is deterministic given the same (namespace, name)
# pair, so this value must never change - changing it would silently
# "rename" (i.e. orphan and duplicate) every seeded row on next run.
SEED_NAMESPACE: uuid.UUID = uuid.uuid5(uuid.NAMESPACE_DNS, "karwan-e-khizr.dev-seed")


def agency_id(key: str) -> uuid.UUID:
    """Deterministic Agency.id for a seed agency's stable `key`."""
    return uuid.uuid5(SEED_NAMESPACE, f"agency:{key}")


def stop_id(key: str) -> uuid.UUID:
    """Deterministic Stop.id for a seed stop's stable `key`."""
    return uuid.uuid5(SEED_NAMESPACE, f"stop:{key}")


def route_id(key: str) -> uuid.UUID:
    """Deterministic Route.id for a seed route's stable `key`."""
    return uuid.uuid5(SEED_NAMESPACE, f"route:{key}")


def route_stop_id(route_key: str, sequence: int) -> uuid.UUID:
    """Deterministic RouteStop.id for a (route, sequence) pair - sequence
    (not stop key) disambiguates a route that legitimately revisits the
    same physical stop twice."""
    return uuid.uuid5(SEED_NAMESPACE, f"route_stop:{route_key}:{sequence}")


@dataclass(frozen=True)
class SeedAgency:
    key: str
    name: str
    network_type: str | None


@dataclass(frozen=True)
class SeedStop:
    key: str
    name: str
    # WGS84 degrees. Longitude/latitude order matches the WKT convention
    # used to build `Stop.location` (see `seeding.seed`), i.e. (x, y).
    latitude: float
    longitude: float


@dataclass(frozen=True)
class SeedRoute:
    key: str
    agency_key: str
    short_name: str
    long_name: str | None
    color: str | None
    # Ordered stop keys - position in this tuple is the route's stop
    # sequence (1-based), matching `RouteStop.sequence`'s semantics.
    stop_keys: tuple[str, ...]


# ---------------------------------------------------------------------------
# Agencies
# ---------------------------------------------------------------------------

SEED_AGENCIES: tuple[SeedAgency, ...] = (
    SeedAgency(key="islamabad_metrobus", name="Islamabad Metrobus", network_type="brt"),
    SeedAgency(key="rawalpindi_metrobus", name="Rawalpindi Metrobus", network_type="brt"),
    SeedAgency(key="cda_feeder", name="CDA Feeder Network", network_type="feeder"),
)

# ---------------------------------------------------------------------------
# Stops (approximate coordinates for real Islamabad/Rawalpindi locations -
# see the Limitations section of backend/data/README.md)
# ---------------------------------------------------------------------------

SEED_STOPS: tuple[SeedStop, ...] = (
    # Islamabad Metrobus (blue line) corridor, north to south.
    SeedStop(key="pak_secretariat", name="Pak Secretariat", latitude=33.7288, longitude=73.0913),
    SeedStop(key="poly_clinic", name="Poly Clinic", latitude=33.7192, longitude=73.0836),
    SeedStop(key="melody", name="Melody", latitude=33.7107, longitude=73.0784),
    SeedStop(key="parade_avenue", name="Parade Avenue Chowk", latitude=33.7040, longitude=73.0722),
    SeedStop(key="pims", name="PIMS", latitude=33.6988, longitude=73.0653),
    SeedStop(key="faizabad", name="Faizabad", latitude=33.6873, longitude=73.0551),
    # Rawalpindi Metrobus (red line) corridor, continuing south from
    # Faizabad (the interchange stop, listed once above and reused here).
    SeedStop(key="ijp_road", name="IJP Road", latitude=33.6817, longitude=73.0490),
    SeedStop(key="khayaban_e_johar", name="Khayaban-e-Johar", latitude=33.6760, longitude=73.0430),
    SeedStop(key="chandni_chowk", name="Chandni Chowk", latitude=33.6700, longitude=73.0390),
    SeedStop(key="faiz_ahmed_faiz", name="Faiz Ahmed Faiz Chowk", latitude=33.6650, longitude=73.0345),
    SeedStop(key="kachehri_chowk", name="Kachehri Chowk", latitude=33.6610, longitude=73.0400),
    SeedStop(key="committee_chowk", name="Committee Chowk", latitude=33.6570, longitude=73.0450),
    SeedStop(key="marir_chowk", name="Marir Chowk", latitude=33.6510, longitude=73.0470),
    SeedStop(key="saddar", name="Saddar", latitude=33.6460, longitude=73.0480),
    # CDA feeder network.
    SeedStop(key="bank_road", name="Bank Road", latitude=33.6440, longitude=73.0460),
    SeedStop(key="liaquat_bagh", name="Liaquat Bagh", latitude=33.6395, longitude=73.0480),
    SeedStop(key="ammar_chowk", name="Ammar Chowk", latitude=33.6350, longitude=73.0510),
    SeedStop(key="g9_markaz", name="G-9 Markaz", latitude=33.7050, longitude=73.0850),
    SeedStop(key="g10_markaz", name="G-10 Markaz", latitude=33.6980, longitude=73.0900),
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

SEED_ROUTES: tuple[SeedRoute, ...] = (
    SeedRoute(
        key="blue_line",
        agency_key="islamabad_metrobus",
        short_name="BL",
        long_name="Pak Secretariat - Faizabad",
        color="#1565C0",
        stop_keys=(
            "pak_secretariat",
            "poly_clinic",
            "melody",
            "parade_avenue",
            "pims",
            "faizabad",
        ),
    ),
    SeedRoute(
        key="red_line",
        agency_key="rawalpindi_metrobus",
        short_name="RL",
        long_name="Faizabad - Saddar",
        color="#C62828",
        stop_keys=(
            "faizabad",
            "ijp_road",
            "khayaban_e_johar",
            "chandni_chowk",
            "faiz_ahmed_faiz",
            "kachehri_chowk",
            "committee_chowk",
            "marir_chowk",
            "saddar",
        ),
    ),
    SeedRoute(
        key="feeder_south",
        agency_key="cda_feeder",
        short_name="F-1",
        long_name="Bank Road - Ammar Chowk Feeder",
        color="#2E7D32",
        stop_keys=("bank_road", "liaquat_bagh", "ammar_chowk"),
    ),
    SeedRoute(
        key="feeder_west",
        agency_key="cda_feeder",
        short_name="F-2",
        long_name="G-9 Markaz - Melody - G-10 Markaz Feeder",
        color="#F9A825",
        stop_keys=("g9_markaz", "melody", "g10_markaz"),
    ),
)


def stops_by_key() -> dict[str, SeedStop]:
    return {stop.key: stop for stop in SEED_STOPS}


def agencies_by_key() -> dict[str, SeedAgency]:
    return {agency.key: agency for agency in SEED_AGENCIES}
