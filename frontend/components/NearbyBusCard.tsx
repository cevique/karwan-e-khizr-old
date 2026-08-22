import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { RouteCircle } from "@/components/ui/RouteCircle";
import { colors, spacing, type } from "@/constants/theme";
import { formatDistance } from "@/utils/geo";
import { etaMinutes } from "@/utils/time";
import type { VehiclePositionRead } from "@/types/api";

interface NearbyBusCardProps {
  vehicle: VehiclePositionRead;
  distanceMeters?: number | null;
  onPress?: () => void;
}

const ARRIVING_SOON_MIN = 5;

export function NearbyBusCard({ vehicle, distanceMeters, onPress }: NearbyBusCardProps) {
  const minutes = etaMinutes(vehicle.estimated_arrival_next_stop);
  const arrivingSoon = minutes !== null && minutes < ARRIVING_SOON_MIN;
  return (
    <TouchableOpacity style={styles.row} onPress={onPress} activeOpacity={0.6}>
      <RouteCircle label={vehicle.route_short_name ?? "?"} />
      <View style={styles.middle}>
        <Text style={styles.routeName} numberOfLines={1}>
          {vehicle.next_stop_name ?? "En route"}
        </Text>
        <Text style={styles.meta}>Next stop</Text>
      </View>
      <View style={styles.right}>
        <Text style={[styles.eta, arrivingSoon && styles.etaSoon]}>
          {minutes !== null ? `${minutes} min` : "--"}
        </Text>
        {distanceMeters !== null && distanceMeters !== undefined && (
          <Text style={styles.meta}>{formatDistance(distanceMeters)}</Text>
        )}
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.base,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
  },
  middle: {
    flex: 1,
    gap: 2,
  },
  routeName: {
    ...type.heading,
    color: colors.textPrimary,
  },
  meta: {
    ...type.caption,
    color: colors.textSecondary,
  },
  right: {
    alignItems: "flex-end",
  },
  eta: {
    ...type.heading,
    color: colors.textPrimary,
  },
  etaSoon: {
    color: colors.warningLive,
  },
});
