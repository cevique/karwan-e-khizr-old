import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { RouteCircle } from "@/components/ui/RouteCircle";
import { colors, spacing, type } from "@/constants/theme";
import { getRoute } from "@/services/transit";
import type { RouteDetail } from "@/types/api";

export default function RouteDetailScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { routeId } = useLocalSearchParams<{ routeId: string }>();
  const [route, setRoute] = useState<RouteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!routeId) return;
    let cancelled = false;
    getRoute(routeId)
      .then((data) => {
        if (!cancelled) setRoute(data);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load this route.");
      });
    return () => {
      cancelled = true;
    };
  }, [routeId]);

  return (
    <View style={[styles.container, { paddingTop: insets.top }]}>
      <View style={styles.header}>
        <TouchableOpacity style={styles.backButton} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={20} color={colors.textPrimary} />
        </TouchableOpacity>
        <View style={styles.headerInfo}>
          {route ? (
            <>
              <RouteCircle label={route.short_name} size={36} />
              <View style={{ flex: 1 }}>
                <Text style={styles.headerTitle} numberOfLines={1}>
                  {route.long_name ?? route.short_name}
                </Text>
                <Text style={styles.headerMeta}>Operated by {route.agency.name}</Text>
              </View>
            </>
          ) : (
            <Text style={styles.headerTitle}>Route</Text>
          )}
        </View>
      </View>

      {error ? (
        <Text style={styles.stateText}>{error}</Text>
      ) : !route ? (
        <ActivityIndicator style={styles.loader} color={colors.accent} />
      ) : (
        <ScrollView contentContainerStyle={{ paddingBottom: spacing.xxl }}>
          <Text style={styles.sectionLabel}>Stops on this route</Text>
          {route.stops.length === 0 ? (
            <Text style={styles.stateText}>No stops are mapped for this route yet.</Text>
          ) : (
            route.stops.map((routeStop, index) => (
              <View key={`${routeStop.stop.id}-${routeStop.sequence}`} style={styles.stopRow}>
                <View style={styles.sequenceColumn}>
                  <View style={styles.sequenceDot}>
                    <Text style={styles.sequenceText}>{routeStop.sequence}</Text>
                  </View>
                  {index < route.stops.length - 1 && <View style={styles.connectorLine} />}
                </View>
                <View style={styles.stopInfo}>
                  <Text style={styles.stopName}>{routeStop.stop.name}</Text>
                  {routeStop.distance_along_route_m !== null && (
                    <Text style={styles.stopMeta}>
                      {(routeStop.distance_along_route_m / 1000).toFixed(1)} km along route
                    </Text>
                  )}
                </View>
              </View>
            ))
          )}

          <Text style={styles.sectionLabel}>Route shape</Text>
          {route.geometry.coordinates ? (
            <Text style={styles.shapeAvailable}>
              Mapped ({route.geometry.geometry_source ?? "unknown source"})
            </Text>
          ) : (
            <Text style={styles.stateText}>
              A precise map shape for this route isn't available yet.
            </Text>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.surface,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.base,
    paddingBottom: spacing.base,
  },
  backButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.bgPrimary,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.divider,
    alignItems: "center",
    justifyContent: "center",
  },
  headerInfo: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  headerTitle: {
    ...type.heading,
    color: colors.textPrimary,
  },
  headerMeta: {
    ...type.caption,
    color: colors.textSecondary,
  },
  sectionLabel: {
    ...type.micro,
    color: colors.textSecondary,
    marginTop: spacing.lg,
    marginBottom: spacing.sm,
    marginHorizontal: spacing.lg,
  },
  stopRow: {
    flexDirection: "row",
    marginHorizontal: spacing.lg,
  },
  sequenceColumn: {
    alignItems: "center",
    marginRight: spacing.base,
  },
  sequenceDot: {
    width: 24,
    height: 24,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: colors.textPrimary,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
  },
  sequenceText: {
    ...type.micro,
    fontWeight: "700",
    color: colors.textPrimary,
  },
  connectorLine: {
    width: 1.5,
    flex: 1,
    minHeight: 16,
    backgroundColor: colors.divider,
  },
  stopInfo: {
    flex: 1,
    paddingTop: 2,
    paddingBottom: spacing.md,
  },
  stopName: {
    ...type.body,
    color: colors.textPrimary,
  },
  stopMeta: {
    ...type.caption,
    color: colors.textSecondary,
    marginTop: 2,
  },
  shapeAvailable: {
    ...type.body,
    color: colors.success,
    marginHorizontal: spacing.lg,
  },
  stateText: {
    ...type.caption,
    color: colors.textSecondary,
    lineHeight: 19,
    marginHorizontal: spacing.lg,
  },
  loader: {
    marginTop: spacing.xl,
  },
});
