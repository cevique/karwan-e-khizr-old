import { DEMO_MODE } from "@/constants/config";
import { demoVehicleEta, demoVehiclePositions } from "@/mocks/demoData";
import { fetchJson } from "./api";
import type {
  ETARead,
  VehicleETAList,
  VehiclePositionRead,
} from "@/types/api";

export function listActiveVehicles(): Promise<VehiclePositionRead[]> {
  if (DEMO_MODE) {
    return Promise.resolve(demoVehiclePositions(Date.now()));
  }
  return fetchJson("/api/transit/realtime/vehicles");
}

export function getVehiclesForRoute(routeId: string): Promise<VehiclePositionRead[]> {
  if (DEMO_MODE) {
    return Promise.resolve(
      demoVehiclePositions(Date.now()).filter(
        (vehicle) => vehicle.route_id === routeId,
      ),
    );
  }
  return fetchJson(`/api/transit/realtime/routes/${routeId}/vehicles`);
}

export function getVehicleEta(vehicleId: string): Promise<VehicleETAList> {
  if (DEMO_MODE) {
    return Promise.resolve(demoVehicleEta(vehicleId, Date.now()));
  }
  return fetchJson(`/api/transit/realtime/vehicles/${vehicleId}/eta`);
}

export type { ETARead, VehiclePositionRead };
