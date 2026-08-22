import { fetchJson } from "./api";
import type {
  ETARead,
  VehicleETAList,
  VehiclePositionRead,
} from "@/types/api";

export function listActiveVehicles(): Promise<VehiclePositionRead[]> {
  return fetchJson("/api/transit/realtime/vehicles");
}

export function getVehiclesForRoute(routeId: string): Promise<VehiclePositionRead[]> {
  return fetchJson(`/api/transit/realtime/routes/${routeId}/vehicles`);
}

export function getVehicleEta(vehicleId: string): Promise<VehicleETAList> {
  return fetchJson(`/api/transit/realtime/vehicles/${vehicleId}/eta`);
}

export type { ETARead, VehiclePositionRead };
