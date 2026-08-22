import { useState, useEffect, useCallback } from "react";
import { VehiclePositionRead } from "../types";
import { fetchRealtimeVehicles } from "../services/realtimeService";
import { DEFAULT_REALTIME_POLL_INTERVAL_MS } from "../constants/config";

export interface UseRealtimeVehiclesResult {
  vehicles: VehiclePositionRead[];
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useRealtimeVehicles(
  routeId?: string,
  pollIntervalMs: number = DEFAULT_REALTIME_POLL_INTERVAL_MS
): UseRealtimeVehiclesResult {
  const [vehicles, setVehicles] = useState<VehiclePositionRead[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const data = await fetchRealtimeVehicles(routeId);
      setVehicles(data);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load vehicle telemetry");
    } finally {
      setLoading(false);
    }
  }, [routeId]);

  useEffect(() => {
    loadData();
    if (pollIntervalMs <= 0) return;

    const interval = setInterval(loadData, pollIntervalMs);
    return () => clearInterval(interval);
  }, [loadData, pollIntervalMs]);

  return {
    vehicles,
    loading,
    error,
    refetch: loadData,
  };
}
