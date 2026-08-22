import { haversineMeters } from "@/utils/geo";
import type {
  AgencyRead,
  Coordinates,
  ETARead,
  JourneyRead,
  RideLegRead,
  RouteListItem,
  RoutingObjective,
  StopRead,
  VehicleETAList,
  VehiclePositionRead,
} from "@/types/api";
import type { JourneySearchRequest } from "@/types/api";

export interface DemoListStopsParams {
  latitude?: number;
  longitude?: number;
  radiusM?: number;
  limit?: number;
  offset?: number;
}

const WALK_SPEED_MPS = 1.2;
const DEMO_SPEED_KMH = 24;
const AT_STOP_THRESHOLD_M = 20;

const DEMO_AGENCY: AgencyRead = {
  id: "demo-agency-pmta",
  name: "Punjab Mass Transit Authority (PMTA)",
  network_type: "brt",
};

interface DemoStopSeed {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
}

const DEMO_STOP_SEEDS: DemoStopSeed[] = [
  { id: "demo-stop-secretariat", name: "Pak Secretariat", latitude: 33.7005, longitude: 73.0525 },
  { id: "demo-stop-pims", name: "PIMS (Pakistan Institute of Medical Sciences)", latitude: 33.6933, longitude: 73.051 },
  { id: "demo-stop-khayaban", name: "Khayaban-e-Johar", latitude: 33.681, longitude: 73.05 },
  { id: "demo-stop-faizabad", name: "Faizabad", latitude: 33.671, longitude: 73.056 },
  { id: "demo-stop-ijp", name: "IJP Road", latitude: 33.66, longitude: 73.052 },
  { id: "demo-stop-chandni", name: "Chandni Chowk", latitude: 33.655, longitude: 73.049 },
  { id: "demo-stop-marrir", name: "Marrir Chowk", latitude: 33.651, longitude: 73.047 },
  { id: "demo-stop-saddar", name: "Saddar", latitude: 33.646, longitude: 73.048 },
];

const DEMO_STOPS: StopRead[] = DEMO_STOP_SEEDS.map((seed) => ({
  id: seed.id,
  name: seed.name,
  location: { latitude: seed.latitude, longitude: seed.longitude },
  distance_m: null,
}));

const STOPS_BY_ID = new Map(DEMO_STOPS.map((stop) => [stop.id, stop]));

export const DEMO_ROUTES: RouteListItem[] = [
  {
    id: "demo-route-red",
    agency_id: DEMO_AGENCY.id,
    short_name: "Red",
    long_name: "Pak Secretariat - Saddar",
    color: "#C62828",
  },
];

const RED_LINE_STOP_IDS = [
  "demo-stop-secretariat",
  "demo-stop-pims",
  "demo-stop-khayaban",
  "demo-stop-faizabad",
  "demo-stop-ijp",
  "demo-stop-chandni",
  "demo-stop-marrir",
  "demo-stop-saddar",
];

function redLineCoordinates(): [number, number][] {
  return RED_LINE_STOP_IDS.map((id) => {
    const stop = STOPS_BY_ID.get(id)!;
    return [stop.location!.longitude, stop.location!.latitude] as [number, number];
  });
}

function cumulativeDistances(coords: Coordinates[]): number[] {
  const cum = [0];
  for (let i = 1; i < coords.length; i += 1) {
    cum.push(cum[i - 1] + haversineMeters(coords[i - 1], coords[i]));
  }
  return cum;
}

function nearestStop(point: Coordinates): StopRead {
  let best = DEMO_STOPS[0];
  let bestDistance = Infinity;
  for (const stop of DEMO_STOPS) {
    const distance = haversineMeters(point, stop.location!);
    if (distance < bestDistance) {
      best = stop;
      bestDistance = distance;
    }
  }
  return best;
}

function walkDuration(distanceM: number): number {
  return distanceM / WALK_SPEED_MPS;
}

export function demoListStops(params: DemoListStopsParams): StopRead[] {
  let stops = DEMO_STOPS;
  if (params.latitude != null && params.longitude != null) {
    const origin = { latitude: params.latitude, longitude: params.longitude };
    stops = stops
      .map((stop) => ({
        ...stop,
        distance_m: haversineMeters(origin, stop.location!),
      }))
      .filter(
        (stop) => params.radiusM == null || (stop.distance_m ?? 0) <= params.radiusM,
      )
      .sort((a, b) => (a.distance_m ?? 0) - (b.distance_m ?? 0));
  }
  const offset = params.offset ?? 0;
  const limit = params.limit ?? stops.length;
  return stops.slice(offset, offset + limit).map((stop) => ({ ...stop }));
}

export function demoJourneySearch(request: JourneySearchRequest): { journeys: JourneyRead[] } {
  const pathCumulative = cumulativeDistances(PATH_COORDINATES);
  const boardIndex = DEMO_STOP_SEEDS.findIndex(
    (seed) => seed.id === nearestStop(request.origin).id,
  );
  let alightIndex = DEMO_STOP_SEEDS.findIndex(
    (seed) => seed.id === nearestStop(request.destination).id,
  );
  if (alightIndex === boardIndex) {
    alightIndex = Math.min(alightIndex + 1, DEMO_STOP_SEEDS.length - 1);
  }
  const boardStop = DEMO_STOPS[boardIndex];
  const alightStop = DEMO_STOPS[alightIndex];

  const walkToBoardM = haversineMeters(request.origin, boardStop.location!);
  const rideM = pathCumulative[alightIndex] - pathCumulative[boardIndex];
  const walkFromAlightM = haversineMeters(alightStop.location!, request.destination);

  const intermediateStops = DEMO_STOPS.slice(boardIndex + 1, alightIndex).map(
    (stop) => ({ ...stop }),
  );
  const speedMps = (DEMO_SPEED_KMH * 1000) / 3600;

  const rideLeg: RideLegRead = {
    type: "ride",
    route: { ...DEMO_ROUTES[0] },
    agency: { ...DEMO_AGENCY },
    board_stop: { ...boardStop },
    alight_stop: { ...alightStop },
    intermediate_stops: intermediateStops,
    duration_s: rideM / speedMps + intermediateStops.length * 20,
    route_geometry: {
      type: "LineString",
      coordinates: DEMO_STOPS.slice(boardIndex, alightIndex + 1).map(
        (stop) =>
          [stop.location!.longitude, stop.location!.latitude] as [number, number],
      ),
      geometry_source: "demo",
      geometry_confidence: "simulated",
    },
  };

  const legs: JourneyRead["legs"] = [
    {
      type: "walk",
      from_stop: null,
      to_stop: { ...boardStop },
      from_location: request.origin,
      to_location: boardStop.location!,
      distance_m: Math.round(walkToBoardM),
      duration_s: walkDuration(walkToBoardM),
    },
    rideLeg,
    {
      type: "walk",
      from_stop: { ...alightStop },
      to_stop: null,
      from_location: alightStop.location!,
      to_location: request.destination,
      distance_m: Math.round(walkFromAlightM),
      duration_s: walkDuration(walkFromAlightM),
    },
  ];

  const objective: RoutingObjective = request.objective ?? "fastest";
  const journey: JourneyRead = {
    objective,
    total_duration_s:
      walkDuration(walkToBoardM) +
      rideLeg.duration_s +
      walkDuration(walkFromAlightM),
    total_walk_m: Math.round(walkToBoardM + walkFromAlightM),
    transfer_count: 0,
    legs,
  };

  return { journeys: [journey] };
}

interface VehiclePathSample {
  coordinate: Coordinates;
  bearing: number | null;
  segmentIndex: number;
  forward: boolean;
  distanceAlongM: number;
  atStopId: string | null;
}

const PATH_COORDINATES: Coordinates[] = RED_LINE_STOP_IDS.map((id) => STOPS_BY_ID.get(id)!.location!);
const PATH_CUMULATIVE = cumulativeDistances(PATH_COORDINATES);
const PATH_TOTAL_M = PATH_CUMULATIVE[PATH_CUMULATIVE.length - 1];
const SPEED_MPS = (DEMO_SPEED_KMH * 1000) / 3600;
const LOOP_SECONDS = (2 * PATH_TOTAL_M) / SPEED_MPS;

function samplePath(distanceAlongM: number): VehiclePathSample {
  const wrapped = ((distanceAlongM % (2 * PATH_TOTAL_M)) + 2 * PATH_TOTAL_M) % (2 * PATH_TOTAL_M);
  const forward = wrapped <= PATH_TOTAL_M;
  const d = forward ? wrapped : 2 * PATH_TOTAL_M - wrapped;

  let segmentIndex = 0;
  while (
    segmentIndex < PATH_CUMULATIVE.length - 2 &&
    PATH_CUMULATIVE[segmentIndex + 1] < d
  ) {
    segmentIndex += 1;
  }
  const from = PATH_COORDINATES[segmentIndex];
  const to = PATH_COORDINATES[segmentIndex + 1];
  const segmentLength = PATH_CUMULATIVE[segmentIndex + 1] - PATH_CUMULATIVE[segmentIndex] || 1;
  const t = (d - PATH_CUMULATIVE[segmentIndex]) / segmentLength;

  const latDelta = to.latitude - from.latitude;
  const lngDelta = (to.longitude - from.longitude) * Math.cos((from.latitude * Math.PI) / 180);
  const rawBearing = (Math.atan2(lngDelta, latDelta) * 180) / Math.PI;
  const bearing = (((forward ? rawBearing : rawBearing + 180) % 360) + 360) % 360;

  let atStopId: string | null = null;
  for (let i = 0; i < PATH_CUMULATIVE.length; i += 1) {
    if (Math.abs(PATH_CUMULATIVE[i] - d) < AT_STOP_THRESHOLD_M) {
      atStopId = RED_LINE_STOP_IDS[i];
    }
  }

  return {
    coordinate: {
      latitude: from.latitude + latDelta * t,
      longitude: from.longitude + (to.longitude - from.longitude) * t,
    },
    bearing: Number.isFinite(bearing) ? bearing : null,
    segmentIndex,
    forward,
    distanceAlongM: d,
    atStopId,
  };
}

function upcomingStopIndices(sample: VehiclePathSample): number[] {
  const indices: number[] = [];
  if (sample.forward) {
    for (let i = 0; i < PATH_CUMULATIVE.length; i += 1) {
      if (PATH_CUMULATIVE[i] > sample.distanceAlongM) indices.push(i);
    }
  } else {
    for (let i = PATH_CUMULATIVE.length - 1; i >= 0; i -= 1) {
      if (PATH_CUMULATIVE[i] < sample.distanceAlongM) indices.push(i);
    }
  }
  return indices;
}

export function demoVehiclePositions(nowMs: number): VehiclePositionRead[] {
  const vehicles: VehiclePositionRead[] = [];
  const fleetCount = 3;
  for (let i = 0; i < fleetCount; i += 1) {
    const vehicleId = `demo-vehicle-red-${i + 1}`;
    const elapsedSeconds = (nowMs / 1000) % LOOP_SECONDS;
    const phaseSeconds = (i / fleetCount) * LOOP_SECONDS;
    const traveledM = ((elapsedSeconds + phaseSeconds) * SPEED_MPS) % (2 * PATH_TOTAL_M);
    const sample = samplePath(traveledM);
    const upcoming = upcomingStopIndices(sample);
    const nextIndex = upcoming[0] ?? (sample.forward ? RED_LINE_STOP_IDS.length - 1 : 0);
    const secondsToNext =
      Math.abs(PATH_CUMULATIVE[nextIndex] - sample.distanceAlongM) / SPEED_MPS;
    const asOfIso = new Date(nowMs).toISOString();

    vehicles.push({
      vehicle_id: vehicleId,
      trip_id: `demo-trip-red-${i + 1}`,
      route_id: DEMO_ROUTES[0].id,
      route_short_name: DEMO_ROUTES[0].short_name,
      route_color: DEMO_ROUTES[0].color,
      location: sample.coordinate,
      bearing: Math.round(sample.bearing ?? 0),
      speed_kmh: DEMO_SPEED_KMH,
      status: sample.atStopId ? "at_stop" : "en_route",
      current_stop_id: sample.atStopId,
      current_stop_name: sample.atStopId
        ? STOPS_BY_ID.get(sample.atStopId)?.name ?? null
        : null,
      next_stop_id: RED_LINE_STOP_IDS[nextIndex],
      next_stop_name: STOPS_BY_ID.get(RED_LINE_STOP_IDS[nextIndex])?.name ?? null,
      scheduled_arrival_next_stop: asOfIso,
      estimated_arrival_next_stop: new Date(nowMs + secondsToNext * 1000).toISOString(),
      delay_seconds: 0,
      elapsed_s: Math.round(traveledM / SPEED_MPS),
      as_of: asOfIso,
    });
  }
  return vehicles;
}

export function demoVehicleEta(vehicleId: string, nowMs: number): VehicleETAList {
  const fleetMatch = /^demo-vehicle-red-(\d+)$/.exec(vehicleId);
  const fallbackNow = demoVehiclePositions(nowMs)[0];
  if (!fleetMatch) {
    return { vehicle_id: vehicleId, trip_id: fallbackNow.trip_id, etas: [] };
  }
  const index = Number(fleetMatch[1]) - 1;
  const elapsedSeconds = (nowMs / 1000) % LOOP_SECONDS;
  const phaseSeconds = (index / 3) * LOOP_SECONDS;
  const traveledM = ((elapsedSeconds + phaseSeconds) * SPEED_MPS) % (2 * PATH_TOTAL_M);
  const sample = samplePath(traveledM);
  const etas: ETARead[] = upcomingStopIndices(sample)
    .slice(0, 5)
    .map((stopIndex, rank) => {
      const secondsAhead =
        Math.abs(PATH_CUMULATIVE[stopIndex] - sample.distanceAlongM) / SPEED_MPS;
      const arrivalIso = new Date(nowMs + secondsAhead * 1000).toISOString();
      return {
        stop_id: RED_LINE_STOP_IDS[stopIndex],
        stop_name: STOPS_BY_ID.get(RED_LINE_STOP_IDS[stopIndex])?.name ?? "",
        sequence: stopIndex + 1,
        scheduled_arrival: arrivalIso,
        estimated_arrival: arrivalIso,
        delay_seconds: rank === 0 ? 0 : rank * 10,
      };
    });
  return { vehicle_id: vehicleId, trip_id: `demo-trip-red-${index + 1}`, etas };
}

