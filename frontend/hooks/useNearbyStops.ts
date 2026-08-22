import { useState, useEffect, useCallback } from "react";
import { StopRead } from "../types";
import { fetchStops } from "../services/transitService";

export interface UseNearbyStopsResult {
  stops: StopRead[];
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function useNearbyStops(
  latitude?: number,
  longitude?: number,
  radiusM: number = 2000
): UseNearbyStopsResult {
  const [stops, setStops] = useState<StopRead[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadStops = useCallback(async () => {
    try {
      setLoading(true);
      const data = await fetchStops(latitude, longitude, radiusM);
      setStops(data);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load stops");
    } finally {
      setLoading(false);
    }
  }, [latitude, longitude, radiusM]);

  useEffect(() => {
    loadStops();
  }, [loadStops]);

  return {
    stops,
    loading,
    error,
    refetch: loadStops,
  };
}
