import { useEffect, useRef, useState } from "react";
import { listStops } from "@/services/transit";
import type { Coordinates, StopRead } from "@/types/api";
import { haversineMeters } from "@/utils/geo";

const NEARBY_STOPS_RADIUS_M = 1500;
const NEARBY_STOPS_LIMIT = 20;
const REFETCH_DISTANCE_M = 200;

export function useNearbyStops(location: Coordinates | null): StopRead[] {
  const [stops, setStops] = useState<StopRead[]>([]);
  const fetchOriginRef = useRef<Coordinates | null>(null);

  useEffect(() => {
    if (!location) return;
    const previous = fetchOriginRef.current;
    if (
      previous &&
      haversineMeters(previous, location) < REFETCH_DISTANCE_M
    ) {
      return;
    }
    fetchOriginRef.current = location;
    let cancelled = false;
    listStops({
      latitude: location.latitude,
      longitude: location.longitude,
      radiusM: NEARBY_STOPS_RADIUS_M,
      limit: NEARBY_STOPS_LIMIT,
    })
      .then((result) => {
        if (!cancelled) {
          setStops(result.filter((stop) => stop.location !== null));
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [location]);

  return stops;
}
