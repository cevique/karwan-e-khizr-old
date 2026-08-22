export interface Coordinates {
  latitude: number;
  longitude: number;
}

export interface AgencyRead {
  id: string;
  name: string;
  network_type: string | null;
}

export interface RouteListItem {
  id: string;
  agency_id: string;
  short_name: string;
  long_name: string | null;
  color: string | null;
}

export interface StopRead {
  id: string;
  name: string;
  location: Coordinates | null;
  distance_m: number | null;
}

export interface RouteStopRead {
  sequence: number;
  distance_along_route_m: number | null;
  stop: StopRead;
}

export interface RouteGeometryRead {
  type: "LineString" | null;
  coordinates: [number, number][] | null;
  geometry_source: string | null;
  geometry_confidence: string | null;
}

export interface RouteDetail {
  id: string;
  agency_id: string;
  short_name: string;
  long_name: string | null;
  color: string | null;
  agency: AgencyRead;
  stops: RouteStopRead[];
  geometry: RouteGeometryRead;
}

export type RoutingObjective = "fastest" | "fewest_transfers" | "least_walking";

export interface JourneySearchRequest {
  origin: Coordinates;
  destination: Coordinates;
  objective?: RoutingObjective;
  max_walk_m?: number | null;
  departure_time?: string | null;
}

export interface WalkLegRead {
  type: "walk";
  from_stop: StopRead | null;
  to_stop: StopRead | null;
  from_location: Coordinates;
  to_location: Coordinates;
  distance_m: number;
  duration_s: number;
}

export interface RideLegRead {
  type: "ride";
  route: RouteListItem;
  agency: AgencyRead;
  board_stop: StopRead;
  alight_stop: StopRead;
  intermediate_stops: StopRead[];
  duration_s: number;
  route_geometry: RouteGeometryRead;
}

export type JourneyLegRead = WalkLegRead | RideLegRead;

export interface JourneyRead {
  objective: RoutingObjective;
  total_duration_s: number;
  total_walk_m: number;
  transfer_count: number;
  legs: JourneyLegRead[];
}

export interface JourneySearchResponse {
  journeys: JourneyRead[];
}

export type VehiclePositionStatus =
  | "not_started"
  | "en_route"
  | "at_stop"
  | "completed";

export interface VehiclePositionRead {
  vehicle_id: string;
  trip_id: string;
  route_id: string;
  route_short_name: string | null;
  route_color: string | null;
  location: Coordinates;
  bearing: number | null;
  speed_kmh: number | null;
  status: VehiclePositionStatus;
  current_stop_id: string | null;
  current_stop_name: string | null;
  next_stop_id: string | null;
  next_stop_name: string | null;
  scheduled_arrival_next_stop: string | null;
  estimated_arrival_next_stop: string | null;
  delay_seconds: number | null;
  elapsed_s: number;
  as_of: string;
}

export interface ETARead {
  stop_id: string;
  stop_name: string;
  sequence: number;
  scheduled_arrival: string;
  estimated_arrival: string;
  delay_seconds: number;
}

export interface VehicleETAList {
  vehicle_id: string;
  trip_id: string;
  etas: ETARead[];
}
