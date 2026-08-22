import React from "react";
import { View, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { VehiclePositionRead } from "../../types";
import { colors, spacing } from "../../constants/theme";
import { Text } from "../design-system/Text";
import { RouteBadge } from "./RouteBadge";
import { formatETA, formatSpeed } from "../../utils/format";

export interface NearbyBusCardProps {
  vehicle: VehiclePositionRead;
  onPress?: () => void;
}

export const NearbyBusCard: React.FC<NearbyBusCardProps> = ({ vehicle, onPress }) => {
  // Extract route short code badge (e.g. RL, BRT)
  const shortCode = vehicle.route_short_name
    ? vehicle.route_short_name.split(" ")[0]
    : "BUS";

  // Calculate mock ETA minutes
  const etaMinutes = Math.max(
    1,
    Math.round(
      (new Date(vehicle.estimated_arrival_next_stop || Date.now() + 180000).getTime() -
        Date.now()) /
        60000
    )
  );

  return (
    <Pressable
      style={({ pressed }) => [styles.container, pressed && styles.pressed]}
      onPress={onPress}
    >
      <View style={styles.leftRow}>
        <RouteBadge
          shortName={shortCode}
          color={vehicle.route_color}
          variant="circle"
          size="md"
        />
        <View style={styles.infoCol}>
          <Text variant="heading" numberOfLines={1}>
            {vehicle.route_short_name || "Transit Route"}
          </Text>
          <Text variant="caption" color={colors.textSecondary} numberOfLines={1}>
            Next stop: {vehicle.next_stop_name || "Approaching..."}
          </Text>
        </View>
      </View>

      <View style={styles.rightCol}>
        <View style={styles.etaRow}>
          <Text variant="heading" color={colors.textPrimary} weight="700">
            {formatETA(etaMinutes)}
          </Text>
          <Ionicons name="radio-outline" size={14} color={colors.success} style={styles.liveIcon} />
        </View>
        <Text variant="caption" color={colors.textTertiary} align="right">
          {formatSpeed(vehicle.speed_kmh)}
        </Text>
      </View>
    </Pressable>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.base,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  pressed: {
    backgroundColor: colors.surfaceMuted,
  },
  leftRow: {
    flexDirection: "row",
    alignItems: "center",
    flex: 1,
    marginRight: spacing.md,
  },
  infoCol: {
    marginLeft: spacing.md,
    flex: 1,
  },
  rightCol: {
    alignItems: "flex-end",
  },
  etaRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  liveIcon: {
    marginLeft: spacing.xxs + 2,
  },
});
