import { useCallback, useEffect, useRef, useState } from "react";
import { useFocusEffect } from "expo-router";
import { listActiveVehicles } from "@/services/realtime";
import type { VehiclePositionRead } from "@/types/api";

interface UseRealtimeVehiclesOptions {
  enabled?: boolean;
}

interface UseRealtimeVehiclesResult {
  vehicles: VehiclePositionRead[];
  isLoading: boolean;
  error: Error | null;
  refresh: () => void;
}

export function useRealtimeVehicles(
  intervalMs: number,
  options: UseRealtimeVehiclesOptions = {},
): UseRealtimeVehiclesResult {
  const { enabled = true } = options;
  const [vehicles, setVehicles] = useState<VehiclePositionRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const hasLoadedRef = useRef(false);
  const [tick, setTick] = useState(0);

  useFocusEffect(
    useCallback(() => {
      if (!enabled) return;
      let cancelled = false;

      async function poll() {
        try {
          const positions = await listActiveVehicles();
          if (cancelled) return;
          setVehicles(positions);
          setError(null);
          hasLoadedRef.current = true;
          setIsLoading(false);
        } catch (cause) {
          if (cancelled) return;
          setError(cause instanceof Error ? cause : new Error(String(cause)));
          setIsLoading(false);
        }
      }

      if (!hasLoadedRef.current) {
        setIsLoading(true);
      }
      void poll();
      const timer = setInterval(poll, intervalMs);

      return () => {
        cancelled = true;
        clearInterval(timer);
      };
    }, [enabled, intervalMs, tick]),
  );

  useEffect(() => {
    return () => {
      hasLoadedRef.current = false;
    };
  }, []);

  const refresh = useCallback(() => setTick((value) => value + 1), []);

  return { vehicles, isLoading, error, refresh };
}
