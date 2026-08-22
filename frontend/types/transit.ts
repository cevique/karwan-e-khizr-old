import { Location, GeoCoordinates } from "./common";

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

export interface RouteGeometryRead {
  type: "LineString" | null;
  coordinates: GeoCoordinates[] | null;
  geometry_source: string | null;
  geometry_confidence: string | null;
}

export interface StopRead {
  id: string;
  name: string;
  location: Location | null;
  distance_m?: number | null;
}

export interface RouteStopSequence {
  sequence: number;
  distance_along_route_m: number | null;
  stop: StopRead;
}

export interface RouteDetail {
  id: string;
  agency_id: string;
  short_name: string;
  long_name: string | null;
  color: string | null;
  agency: AgencyRead;
  stops: RouteStopSequence[];
  geometry: RouteGeometryRead;
}
