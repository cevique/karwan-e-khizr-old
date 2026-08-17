"""
Nominatim-based geocoding for filling null `Stop.location` coordinates
(plan.md section C, Phase 2 - Geospatial Enrichment).

Only stops the canonical `docs/transit_data.json` dataset leaves without
coordinates (~105 of 122, see `docs/DATA_GAPS.md`) are candidates here.
Stops that already have a location (the 17 SEED_DATUM/APPROXIMATE rows -
see `seeding.importer._get_or_create_stop`) are never touched or
overwritten by this module; `scripts/geocode_stops.py` enforces that by
only ever querying `Stop.location IS NULL` rows in the first place.

`Geocoder` is a small Protocol (the same shape as
`ticketing.payments.provider.PaymentProvider`) so tests and the CLI
script can be exercised without any network access, using a fake that
returns canned results; `NominatimGeocoder` is the only real
implementation, wrapping OpenStreetMap's public Nominatim `/search`
endpoint.

This module never fabricates a coordinate: a query that returns nothing,
or returns only candidates outside the Islamabad/Rawalpindi bounding box,
resolves to `None` - callers (`scripts/geocode_stops.py`) leave
`Stop.location` NULL and record `coordinate_confidence = "UNKNOWN"`
rather than guessing.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

# Nominatim's usage policy
# (https://operations.osmfoundation.org/policies/nominatim/) requires:
# at most 1 request/second, a descriptive User-Agent identifying the
# application (not a generic HTTP client string), and no parallel
# requests - all enforced by `NominatimGeocoder` below.
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "karwan-e-khizr-transit-geocoder/1.0 (+backend/seeding/geocoding.py)"
MIN_REQUEST_INTERVAL_S = 1.0

# Islamabad/Rawalpindi bounding box (plan.md section C). A geocode result
# outside this box is treated as no match at all rather than accepted -
# ambiguous or common stop names ("6th Road", "Bank Road") must not
# silently resolve to a same-named place in another city.
BBOX_MIN_LAT = 33.5
BBOX_MAX_LAT = 33.85
BBOX_MIN_LON = 73.0
BBOX_MAX_LON = 73.3


@dataclass(frozen=True)
class GeocodeResult:
    """One accepted geocoding match, already validated to be inside the
    Islamabad/Rawalpindi bounding box."""

    latitude: float
    longitude: float
    display_name: str


class GeocodingError(Exception):
    """The geocoding request itself failed (network/HTTP error) -
    distinct from "no in-bounds match found", which is a normal `None`
    return, not an error."""


class Geocoder(Protocol):
    """Interface a geocoding backend (Nominatim or a test fake) must
    satisfy."""

    async def geocode(self, query: str) -> GeocodeResult | None:
        """Return the best in-bounds match for `query`, or None if the
        backend returned nothing, or nothing it returned falls inside the
        Islamabad/Rawalpindi bounding box. Must never fabricate a
        coordinate; raise `GeocodingError` for a genuine request failure
        rather than returning None for it."""
        ...


def in_bounding_box(latitude: float, longitude: float) -> bool:
    """Whether (latitude, longitude) falls inside the Islamabad/Rawalpindi
    box used to validate geocoding results (plan.md section C)."""
    return BBOX_MIN_LAT <= latitude <= BBOX_MAX_LAT and BBOX_MIN_LON <= longitude <= BBOX_MAX_LON


def query_variants(stop_name: str) -> tuple[str, str]:
    """Two queries to try in order for a stop name: Islamabad first (most
    CDA/metro stops in `transit_data.json` sit there), then Rawalpindi as
    a fallback for the stops that don't."""
    return (
        f"{stop_name}, Islamabad, Pakistan",
        f"{stop_name}, Rawalpindi, Pakistan",
    )


async def geocode_stop_name(geocoder: Geocoder, stop_name: str) -> GeocodeResult | None:
    """Try each of `query_variants(stop_name)` in order against
    `geocoder`, returning the first in-bounds match, or None if none of
    the variants resolve to one."""
    for query in query_variants(stop_name):
        result = await geocoder.geocode(query)
        if result is not None:
            return result
    return None


class NominatimGeocoder:
    """Real `Geocoder`: queries OpenStreetMap's public Nominatim instance
    (`https://nominatim.openstreetmap.org`), the free/no-API-key source
    `plan.md` section C specifies.

    Rate-limited to `min_interval_s` between requests. This class only
    ever issues one request at a time (`scripts/geocode_stops.py` awaits
    each stop in turn - it never fans out), so a simple
    "sleep until enough time has passed since the last call" throttle is
    sufficient; there is no concurrent-request case to guard against.

    Accepts an injected `httpx.AsyncClient` so tests can supply a
    `httpx.MockTransport`-backed client with no real network access; when
    none is given, this class owns and closes its own client.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        base_url: str = NOMINATIM_SEARCH_URL,
        min_interval_s: float = MIN_REQUEST_INTERVAL_S,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=10.0
        )
        self._owns_client = client is None
        self._base_url = base_url
        self._min_interval_s = min_interval_s
        self._last_request_at: float | None = None

    async def __aenter__(self) -> "NominatimGeocoder":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _throttle(self) -> None:
        if self._last_request_at is None:
            return
        wait_s = self._min_interval_s - (time.monotonic() - self._last_request_at)
        if wait_s > 0:
            await asyncio.sleep(wait_s)

    async def geocode(self, query: str) -> GeocodeResult | None:
        await self._throttle()
        try:
            response = await self._client.get(
                self._base_url,
                params={"q": query, "format": "jsonv2", "limit": 5, "addressdetails": 0},
            )
            response.raise_for_status()
            candidates = response.json()
        except httpx.HTTPError as exc:
            raise GeocodingError(f"Nominatim request failed for {query!r}: {exc}") from exc
        finally:
            # Recorded even on failure/exception - a failed request still
            # counted against Nominatim's rate limit, so the next call
            # must still wait out the interval.
            self._last_request_at = time.monotonic()

        # Nominatim ranks by relevance/importance, so the first in-bounds
        # candidate (not necessarily the first candidate overall) is the
        # best match; out-of-bounds candidates ahead of it are silently
        # skipped rather than accepted.
        for candidate in candidates:
            try:
                lat = float(candidate["lat"])
                lon = float(candidate["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            if in_bounding_box(lat, lon):
                return GeocodeResult(
                    latitude=lat,
                    longitude=lon,
                    display_name=candidate.get("display_name", query),
                )
        return None
