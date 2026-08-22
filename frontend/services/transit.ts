import { DEMO_MODE } from "@/constants/config";
import { demoListStops } from "@/mocks/demoData";
import { fetchJson } from "./api";
import type {
  RouteDetail,
  RouteGeometryRead,
  RouteListItem,
  StopRead,
} from "@/types/api";

export interface ListStopsParams {
  latitude?: number;
  longitude?: number;
  radiusM?: number;
  limit?: number;
  offset?: number;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export function listStops(params: ListStopsParams = {}): Promise<StopRead[]> {
  if (DEMO_MODE) {
    return Promise.resolve(demoListStops(params));
  }
  const query = buildQuery({
    latitude: params.latitude,
    longitude: params.longitude,
    radius_m: params.radiusM,
    limit: params.limit,
    offset: params.offset,
  });
  return fetchJson(`/api/transit/stops${query}`);
}

export function getStop(stopId: string): Promise<StopRead> {
  return fetchJson(`/api/transit/stops/${stopId}`);
}

export function listRoutes(agencyId?: string): Promise<RouteListItem[]> {
  const query = buildQuery({ agency_id: agencyId });
  return fetchJson(`/api/transit/routes${query}`);
}

export function getRoute(routeId: string): Promise<RouteDetail> {
  return fetchJson(`/api/transit/routes/${routeId}`);
}

export function getRouteGeometry(routeId: string): Promise<RouteGeometryRead> {
  return fetchJson(`/api/transit/routes/${routeId}/geometry`);
}
