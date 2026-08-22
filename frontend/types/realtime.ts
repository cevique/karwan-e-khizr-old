import { Location } from "./common";

export type VehicleStatus = "not_started" | "en_route" | "at_stop" | "completed";

export interface VehiclePositionRead {
  vehicle_id: string;
  trip_id: string;
  route_id: string;
  route_short_name: string | null;
  route_color: string | null;
  location: Location;
  bearing: number | null;
  speed_kmh: number | null;
  status: VehicleStatus;
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
