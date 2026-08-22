import React, { useEffect, useRef } from "react";
import { StyleSheet, View, ViewStyle } from "react-native";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MAP_STYLE_URL, ISLAMABAD_CENTER } from "../../constants/config";
import { Location, StopRead, VehiclePositionRead } from "../../types";

export interface MapViewProps {
  center?: [number, number];
  zoom?: number;
  stops?: StopRead[];
  vehicles?: VehiclePositionRead[];
  userLocation?: Location | null;
  onStopPress?: (stop: StopRead) => void;
  onVehiclePress?: (vehicle: VehiclePositionRead) => void;
  style?: ViewStyle;
  children?: React.ReactNode;
}

export const WebMapView: React.FC<MapViewProps> = ({
  center = ISLAMABAD_CENTER,
  zoom = 13,
  stops = [],
  vehicles = [],
  userLocation,
  onStopPress,
  onVehiclePress,
  style,
}) => {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markersRef = useRef<maplibregl.Marker[]>([]);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: MAP_STYLE_URL,
      center: center,
      zoom: zoom,
      attributionControl: false,
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Sync Markers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // Clear existing markers
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    // Render User Location
    if (userLocation) {
      const el = document.createElement("div");
      el.className = "user-location-marker";
      el.style.width = "18px";
      el.style.height = "18px";
      el.style.borderRadius = "50%";
      el.style.backgroundColor = "#2563EB";
      el.style.border = "3px solid #FFFFFF";
      el.style.boxShadow = "0 0 10px rgba(37,99,235,0.5)";

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([userLocation.longitude, userLocation.latitude])
        .addTo(map);
      markersRef.current.push(marker);
    }

    // Render Stops
    stops.forEach((stop) => {
      if (!stop.location) return;
      const el = document.createElement("div");
      el.style.width = "12px";
      el.style.height = "12px";
      el.style.borderRadius = "50%";
      el.style.backgroundColor = "#10B981";
      el.style.border = "2px solid #FFFFFF";
      el.style.cursor = "pointer";
      el.title = stop.name;

      el.addEventListener("click", () => onStopPress?.(stop));

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([stop.location.longitude, stop.location.latitude])
        .addTo(map);
      markersRef.current.push(marker);
    });

    // Render Vehicles
    vehicles.forEach((veh) => {
      const el = document.createElement("div");
      el.style.width = "28px";
      el.style.height = "28px";
      el.style.borderRadius = "14px";
      el.style.backgroundColor = veh.route_color || "#0A6E64";
      el.style.color = "#FFFFFF";
      el.style.display = "flex";
      el.style.alignItems = "center";
      el.style.justifyContent = "center";
      el.style.fontSize = "10px";
      el.style.fontWeight = "bold";
      el.style.border = "2px solid #FFFFFF";
      el.style.boxShadow = "0 2px 6px rgba(0,0,0,0.3)";
      el.style.cursor = "pointer";
      el.innerText = veh.route_short_name ? veh.route_short_name.slice(0, 3) : "BUS";

      el.addEventListener("click", () => onVehiclePress?.(veh));

      const marker = new maplibregl.Marker({ element: el })
        .setLngLat([veh.location.longitude, veh.location.latitude])
        .addTo(map);
      markersRef.current.push(marker);
    });
  }, [stops, vehicles, userLocation]);

  return (
    <View style={[styles.container, style]}>
      <div ref={mapContainerRef} style={{ width: "100%", height: "100%" }} />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
});
