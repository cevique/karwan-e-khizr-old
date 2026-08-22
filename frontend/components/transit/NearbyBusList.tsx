import React from "react";
import { View, StyleSheet, Pressable, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { VehiclePositionRead } from "../../types";
import { colors, radii, spacing, elevation } from "../../constants/theme";
import { Text } from "../design-system/Text";
import { Card } from "../design-system/Card";
import { NearbyBusCard } from "./NearbyBusCard";

export interface NearbyBusListProps {
  vehicles: VehiclePositionRead[];
  onVehiclePress?: (vehicle: VehiclePositionRead) => void;
  onViewAllPress?: () => void;
}

export const NearbyBusList: React.FC<NearbyBusListProps> = ({
  vehicles,
  onVehiclePress,
  onViewAllPress,
}) => {
  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.container} showsVerticalScrollIndicator={false}>
      {/* Drag Handle Indicator */}
      <View style={styles.handleBar} />

      {/* Header */}
      <View style={styles.headerRow}>
        <Text variant="title" color={colors.textPrimary}>
          Nearby Buses
        </Text>
        {onViewAllPress && (
          <Pressable onPress={onViewAllPress}>
            <Text variant="subheading" color={colors.accent}>
              View all
            </Text>
          </Pressable>
        )}
      </View>

      {/* Bus Items List Card */}
      <Card elevationVariant="soft" padding="xxs" style={styles.listCard}>
        {vehicles.length === 0 ? (
          <View style={styles.emptyContainer}>
            <Text variant="body" color={colors.textSecondary} align="center">
              No active buses detected nearby right now.
            </Text>
          </View>
        ) : (
          vehicles.map((veh) => (
            <NearbyBusCard
              key={veh.vehicle_id}
              vehicle={veh}
              onPress={() => onVehiclePress?.(veh)}
            />
          ))
        )}
      </Card>

      {/* Eco Banner ("Travel Green, Live Clean") */}
      <Card elevationVariant="flat" backgroundColor={colors.surfaceEco} style={styles.ecoCard}>
        <View style={styles.ecoContentRow}>
          <View style={styles.leafCircle}>
            <Ionicons name="leaf-outline" size={20} color={colors.textUrdu} />
          </View>
          <View style={styles.ecoTextCol}>
            <Text variant="heading" color={colors.textUrdu} style={styles.ecoTitle}>
              Travel Green, Live Clean
            </Text>
            <Text variant="caption" color={colors.textSecondary}>
              Use public transport and reduce your carbon footprint.
            </Text>
          </View>
          <Ionicons name="bus-outline" size={32} color={colors.success} style={styles.busIllustration} />
        </View>
      </Card>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  scroll: {
    flex: 1,
  },
  container: {
    paddingHorizontal: spacing.base,
    paddingBottom: spacing.xxl,
  },
  handleBar: {
    width: 36,
    height: 4,
    borderRadius: radii.pill,
    backgroundColor: colors.divider,
    alignSelf: "center",
    marginBottom: spacing.md,
    marginTop: spacing.xs,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  listCard: {
    marginBottom: spacing.base,
  },
  emptyContainer: {
    padding: spacing.lg,
  },
  ecoCard: {
    borderRadius: radii.card,
    padding: spacing.base,
    borderWidth: 1,
    borderColor: "rgba(12, 90, 62, 0.12)",
  },
  ecoContentRow: {
    flexDirection: "row",
    alignItems: "center",
  },
  leafCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "rgba(12, 90, 62, 0.1)",
    alignItems: "center",
    justifyContent: "center",
    marginRight: spacing.md,
  },
  ecoTextCol: {
    flex: 1,
  },
  ecoTitle: {
    marginBottom: spacing.xxs,
  },
  busIllustration: {
    opacity: 0.8,
    marginLeft: spacing.sm,
  },
});
