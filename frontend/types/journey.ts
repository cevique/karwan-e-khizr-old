import { Location } from "./common";
import { AgencyRead, RouteListItem, RouteGeometryRead, StopRead } from "./transit";

export type JourneyObjective = "fastest" | "fewest_transfers" | "least_walking";

export interface JourneySearchRequest {
  origin: Location;
  destination: Location;
  objective?: JourneyObjective;
  max_walk_m?: number | null;
  departure_time?: string | null;
}

export interface WalkLegRead {
  type: "walk";
  from_stop: StopRead | null;
  to_stop: StopRead | null;
  from_location: Location;
  to_location: Location;
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
  objective: JourneyObjective;
  total_duration_s: number;
  total_walk_m: number;
  transfer_count: number;
  legs: JourneyLegRead[];
  fare_amount_pkr?: number;
  headway_info?: string;
  is_recommended?: boolean;
}

export interface JourneySearchResponse {
  journeys: JourneyRead[];
}
