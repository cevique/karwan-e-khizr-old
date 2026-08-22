import { AgencyRead, RouteListItem, RouteDetail, StopRead } from "../types";
import { apiRequest } from "./api";
import { DEMO_MODE } from "../constants/config";
import { MOCK_AGENCIES, MOCK_ROUTES, MOCK_ROUTE_DETAILS, MOCK_STOPS } from "../mocks";

export async function fetchAgencies(): Promise<AgencyRead[]> {
  if (DEMO_MODE) return MOCK_AGENCIES;
  try {
    return await apiRequest<AgencyRead[]>("/api/transit/agencies");
  } catch (e) {
    console.warn("API request failed, falling back to mock agencies:", e);
    return MOCK_AGENCIES;
  }
}

export async function fetchRoutes(agencyId?: string): Promise<RouteListItem[]> {
  if (DEMO_MODE) return MOCK_ROUTES;
  try {
    const query = agencyId ? `?agency_id=${agencyId}` : "";
    return await apiRequest<RouteListItem[]>(`/api/transit/routes${query}`);
  } catch (e) {
    console.warn("API request failed, falling back to mock routes:", e);
    return MOCK_ROUTES;
  }
}

export async function fetchRouteDetail(routeId: string): Promise<RouteDetail> {
  if (DEMO_MODE) {
    return MOCK_ROUTE_DETAILS[routeId] || MOCK_ROUTE_DETAILS["route-red-line-01"];
  }
  try {
    return await apiRequest<RouteDetail>(`/api/transit/routes/${routeId}`);
  } catch (e) {
    return MOCK_ROUTE_DETAILS[routeId] || MOCK_ROUTE_DETAILS["route-red-line-01"];
  }
}

export async function fetchStops(
  lat?: number,
  lon?: number,
  radiusM: number = 2000
): Promise<StopRead[]> {
  if (DEMO_MODE) return MOCK_STOPS;
  try {
    const params = new URLSearchParams();
    if (lat !== undefined && lon !== undefined) {
      params.append("latitude", lat.toString());
      params.append("longitude", lon.toString());
      params.append("radius_m", radiusM.toString());
    }
    return await apiRequest<StopRead[]>(`/api/transit/stops?${params.toString()}`);
  } catch (e) {
    return MOCK_STOPS;
  }
}
