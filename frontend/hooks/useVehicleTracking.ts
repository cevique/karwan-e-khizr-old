import { useCallback, useMemo, useState } from "react";
import { useFocusEffect } from "expo-router";
import { useRealtimeVehicles } from "./useRealtimeVehicles";
import { getVehicleEta } from "@/services/realtime";
import type { VehicleETAList, VehiclePositionRead } from "@/types/api";

const VEHICLE_GONE_MESSAGE = "This vehicle is no longer running.";
const CONNECTION_MESSAGE = "Lost connection to the transit server.";

export interface UseVehicleTrackingResult {
  vehicle: VehiclePositionRead | null;
  etas: VehicleETAList | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useVehicleTracking(
  vehicleId: string | undefined,
  intervalMs: number,
): UseVehicleTrackingResult {
  const [etas, setEtas] = useState<VehicleETAList | null>(null);
  const [isFocused, setIsFocused] = useState(false);

  useFocusEffect(
    useCallback(() => {
      setIsFocused(true);
      return () => setIsFocused(false);
    }, []),
  );

  const { vehicles, isLoading, error, refresh } = useRealtimeVehicles(intervalMs, {
    enabled: isFocused,
  });

  useFocusEffect(
    useCallback(() => {
      if (!vehicleId) return;
      let cancelled = false;

      async function pollEtas() {
        try {
          const data = await getVehicleEta(vehicleId!);
          if (cancelled) return;
          setEtas(data);
        } catch {
          if (!cancelled) setEtas(null);
        }
      }

      void pollEtas();
      const timer = setInterval(pollEtas, intervalMs);

      return () => {
        cancelled = true;
        clearInterval(timer);
      };
    }, [intervalMs, vehicleId]),
  );

  const vehicle = useMemo(
    () => vehicles.find((item) => item.vehicle_id === vehicleId) ?? null,
    [vehicles, vehicleId],
  );

  const trackingError = useMemo<string | null>(() => {
    if (error) return CONNECTION_MESSAGE;
    if (!isLoading && !vehicle) return VEHICLE_GONE_MESSAGE;
    return null;
  }, [error, isLoading, vehicle]);

  return { vehicle, etas, isLoading, error: trackingError, refresh };
}
