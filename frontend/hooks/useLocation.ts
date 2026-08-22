import { useEffect, useState } from "react";
import {
  PermissionResponse,
  Accuracy,
  watchPositionAsync,
  requestForegroundPermissionsAsync,
} from "expo-location";
import type { Coordinates } from "@/types/api";

interface UseLocationResult {
  location: Coordinates | null;
  granted: boolean;
  error: string | null;
}

export function useLocation(): UseLocationResult {
  const [location, setLocation] = useState<Coordinates | null>(null);
  const [granted, setGranted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let subscription: ReturnType<typeof watchPositionAsync> extends Promise<infer T>
      ? T | null
      : never;
    let cancelled = false;

    async function start() {
      let permission: PermissionResponse;
      try {
        permission = await requestForegroundPermissionsAsync();
      } catch {
        if (!cancelled) setError("Location is unavailable on this device.");
        return;
      }
      if (cancelled) return;
      setGranted(permission.granted);
      if (!permission.granted) {
        setError("Location permission was not granted.");
        return;
      }
      try {
        subscription = await watchPositionAsync(
          { accuracy: Accuracy.Balanced },
          (position) => {
            if (!cancelled) {
              setLocation({
                latitude: position.coords.latitude,
                longitude: position.coords.longitude,
              });
            }
          },
        );
      } catch {
        if (!cancelled) setError("Could not read your location.");
      }
    }

    void start();
    return () => {
      cancelled = true;
      subscription?.remove();
    };
  }, []);

  return { location, granted, error };
}
