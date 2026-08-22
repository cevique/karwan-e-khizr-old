import React, { useRef } from "react";
import { StyleSheet, View, ViewStyle } from "react-native";
import { Map, Camera, UserLocation as UserLocationMarker, MapRef } from "@maplibre/maplibre-react-native";
import { MAP_STYLE_URL, ISLAMABAD_CENTER } from "../../constants/config";
import { Location, StopRead, VehiclePositionRead } from "../../types";
import { StopMarker } from "./StopMarker";
import { VehicleMarker } from "./VehicleMarker";

export interface MapViewProps {
  center?: [number, number]; // [lon, lat]
  zoom?: number;
  stops?: StopRead[];
  vehicles?: VehiclePositionRead[];
  userLocation?: Location | null;
  onStopPress?: (stop: StopRead) => void;
  onVehiclePress?: (vehicle: VehiclePositionRead) => void;
  style?: ViewStyle;
  children?: React.ReactNode;
}

export const NativeMapView: React.FC<MapViewProps> = ({
  center = ISLAMABAD_CENTER,
  zoom = 13,
  stops = [],
  vehicles = [],
  userLocation,
  onStopPress,
  onVehiclePress,
  style,
  children,
}) => {
  const mapRef = useRef<MapRef>(null);

  return (
    <View style={[styles.container, style]}>
      <Map
        ref={mapRef}
        style={styles.map}
        mapStyle={MAP_STYLE_URL}
      >
        <Camera
          initialViewState={{
            center: center,
            zoom: zoom,
          }}
        />

        {userLocation && <UserLocationMarker />}

        {stops.map((stop) => {
          if (!stop.location) return null;
          return (
            <StopMarker
              key={stop.id}
              stop={stop}
              onPress={() => onStopPress?.(stop)}
            />
          );
        })}

        {vehicles.map((vehicle) => (
          <VehicleMarker
            key={vehicle.vehicle_id}
            vehicle={vehicle}
            onPress={() => onVehiclePress?.(vehicle)}
          />
        ))}

        {children}
      </Map>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  map: {
    flex: 1,
  },
});
