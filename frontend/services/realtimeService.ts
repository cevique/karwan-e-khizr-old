import { VehiclePositionRead, VehicleETAList } from "../types";
import { apiRequest } from "./api";
import { DEMO_MODE } from "../constants/config";
import { MOCK_VEHICLES } from "../mocks";

export async function fetchRealtimeVehicles(routeId?: string): Promise<VehiclePositionRead[]> {
  if (DEMO_MODE) {
    if (routeId) {
      return MOCK_VEHICLES.filter((v) => v.route_id === routeId);
    }
    return MOCK_VEHICLES;
  }
  try {
    const endpoint = routeId
      ? `/api/transit/realtime/routes/${routeId}/vehicles`
      : "/api/transit/realtime/vehicles";
    return await apiRequest<VehiclePositionRead[]>(endpoint);
  } catch (e) {
    return MOCK_VEHICLES;
  }
}

export async function fetchVehicleETA(vehicleId: string): Promise<VehicleETAList | null> {
  if (DEMO_MODE) {
    return {
      vehicle_id: vehicleId,
      trip_id: "demo-trip",
      etas: [
        {
          stop_id: "stop-01",
          stop_name: "PIMS",
          sequence: 1,
          scheduled_arrival: new Date(Date.now() + 60000).toISOString(),
          estimated_arrival: new Date(Date.now() + 60000).toISOString(),
          delay_seconds: 0,
        },
      ],
    };
  }
  try {
    return await apiRequest<VehicleETAList>(`/api/transit/realtime/vehicles/${vehicleId}/eta`);
  } catch (e) {
    return null;
  }
}
