import { useState, useEffect } from "react";
import * as Location from "expo-location";
import { Location as LocationType } from "../types";
import { ISLAMABAD_CENTER } from "../constants/config";

export interface UseLocationResult {
  location: LocationType;
  isDemo: boolean;
  errorMsg: string | null;
  loading: boolean;
  requestPermission: () => Promise<void>;
}

export function useLocation(): UseLocationResult {
  const [location, setLocation] = useState<LocationType>({
    latitude: ISLAMABAD_CENTER[1],
    longitude: ISLAMABAD_CENTER[0],
  });
  const [isDemo, setIsDemo] = useState<boolean>(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const requestPermission = async () => {
    try {
      setLoading(true);
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") {
        setErrorMsg("Permission to access location was denied");
        setIsDemo(true);
        setLoading(false);
        return;
      }

      const currLoc = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Balanced,
      });

      setLocation({
        latitude: currLoc.coords.latitude,
        longitude: currLoc.coords.longitude,
      });
      setIsDemo(false);
      setErrorMsg(null);
    } catch (e: any) {
      setErrorMsg(e.message || "Failed to get current location");
      setIsDemo(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    requestPermission();
  }, []);

  return {
    location,
    isDemo,
    errorMsg,
    loading,
    requestPermission,
  };
}
