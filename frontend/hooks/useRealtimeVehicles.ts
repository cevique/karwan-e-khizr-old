import { useCallback, useEffect, useRef, useState } from "react";
import { listActiveVehicles } from "@/services/realtime";
import type { VehiclePositionRead } from "@/types/api";

interface UseRealtimeVehiclesResult {
  vehicles: VehiclePositionRead[];
  isLoading: boolean;
  error: Error | null;
  refresh: () => void;
}

export function useRealtimeVehicles(
  intervalMs: number,
): UseRealtimeVehiclesResult {
  const [vehicles, setVehicles] = useState<VehiclePositionRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const positions = await listActiveVehicles();
        if (!cancelled && mountedRef.current) {
          setVehicles(positions);
          setError(null);
        }
      } catch (cause) {
        if (!cancelled && mountedRef.current) {
          setError(cause instanceof Error ? cause : new Error(String(cause)));
        }
      } finally {
        if (!cancelled && mountedRef.current) {
          setIsLoading(false);
        }
      }
    }

    setIsLoading(true);
    void poll();
    const timer = setInterval(poll, intervalMs);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [intervalMs, tick]);

  const refresh = useCallback(() => setTick((value) => value + 1), []);

  return { vehicles, isLoading, error, refresh };
}
