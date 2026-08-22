import React from "react";
import { View, StyleSheet, Pressable } from "react-native";
import { Marker } from "@maplibre/maplibre-react-native";
import { Ionicons } from "@expo/vector-icons";
import { VehiclePositionRead } from "../../types";
import { colors, elevation } from "../../constants/theme";

export interface VehicleMarkerProps {
  vehicle: VehiclePositionRead;
  onPress?: () => void;
}

export const VehicleMarker: React.FC<VehicleMarkerProps> = ({ vehicle, onPress }) => {
  const markerColor = vehicle.route_color || colors.accent;
  const rotation = vehicle.bearing || 0;

  return (
    <Marker
      lngLat={[vehicle.location.longitude, vehicle.location.latitude]}
      onPress={onPress}
    >
      <Pressable style={styles.container} onPress={onPress}>
        <View style={[styles.badge, { backgroundColor: markerColor }]}>
          <Ionicons name="bus" size={14} color={colors.textInverse} />
          {rotation > 0 && (
            <View style={[styles.headingArrow, { transform: [{ rotate: `${rotation}deg` }] }]}>
              <Ionicons name="triangle" size={8} color={colors.textInverse} />
            </View>
          )}
        </View>
      </Pressable>
    </Marker>
  );
};

const styles = StyleSheet.create({
  container: {
    alignItems: "center",
    justifyContent: "center",
  },
  badge: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 2,
    borderColor: colors.surface,
    ...elevation.medium,
  },
  headingArrow: {
    position: "absolute",
    top: -6,
  },
});
