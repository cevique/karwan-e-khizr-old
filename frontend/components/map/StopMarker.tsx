import React from "react";
import { View, StyleSheet, Pressable } from "react-native";
import { Marker } from "@maplibre/maplibre-react-native";
import { StopRead } from "../../types";
import { colors } from "../../constants/theme";

export interface StopMarkerProps {
  stop: StopRead;
  onPress?: () => void;
}

export const StopMarker: React.FC<StopMarkerProps> = ({ stop, onPress }) => {
  if (!stop.location) return null;

  return (
    <Marker
      lngLat={[stop.location.longitude, stop.location.latitude]}
      onPress={onPress}
    >
      <Pressable style={styles.container} onPress={onPress}>
        <View style={styles.outerCircle}>
          <View style={styles.innerDot} />
        </View>
      </Pressable>
    </Marker>
  );
};

const styles = StyleSheet.create({
  container: {
    padding: 4,
  },
  outerCircle: {
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: "rgba(27, 158, 119, 0.2)",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.success,
  },
  innerDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.success,
  },
});
