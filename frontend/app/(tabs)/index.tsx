import { Ionicons } from "@expo/vector-icons";
import BottomSheet, { BottomSheetFlatList } from "@gorhom/bottom-sheet";
import { useRouter } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { NearbyBusCard } from "@/components/NearbyBusCard";
import { ScreenShell } from "@/components/ScreenShell";
import {
  MapMarker,
  TransitMapView,
} from "@/components/TransitMapView";
import { DEFAULT_REALTIME_POLL_INTERVAL_MS } from "@/constants/config";
import { colors, spacing, type } from "@/constants/theme";
import { useLocation } from "@/hooks/useLocation";
import { useRealtimeVehicles } from "@/hooks/useRealtimeVehicles";
import { listStops } from "@/services/transit";
import type { StopRead } from "@/types/api";
import { useEffect } from "react";
import { haversineMeters } from "@/utils/geo";

const SHEET_SNAP_POINTS = [140, "45%", "90%"];

export default function HomeScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const sheetRef = useRef<BottomSheet>(null);
  const [recenterSignal, setRecenterSignal] = useState(0);
  const [nearbyStops, setNearbyStops] = useState<StopRead[]>([]);
  const { location } = useLocation();
  const { vehicles, isLoading, error } = useRealtimeVehicles(
    DEFAULT_REALTIME_POLL_INTERVAL_MS,
  );

  useEffect(() => {
    if (!location) return;
    let cancelled = false;
    listStops({
      latitude: location.latitude,
      longitude: location.longitude,
      radiusM: 1500,
      limit: 20,
    })
      .then((stops) => {
        if (!cancelled) setNearbyStops(stops.filter((stop) => stop.location !== null));
      })
      .catch(() => {
        if (!cancelled) setNearbyStops([]);
      });
    return () => {
      cancelled = true;
    };
  }, [location]);

  const markers = useMemo<MapMarker[]>(
    () => [
      ...nearbyStops
        .filter((stop) => stop.location)
        .map((stop) => ({
          id: stop.id,
          coordinate: stop.location!,
          kind: "stop" as const,
          label: stop.name,
        })),
      ...vehicles.map((vehicle) => ({
        id: vehicle.vehicle_id,
        coordinate: vehicle.location,
        kind: "vehicle" as const,
      })),
    ],
    [nearbyStops, vehicles],
  );

  const renderItem = useCallback(
    ({ item }: { item: (typeof vehicles)[number] }) => (
      <View>
        <NearbyBusCard
          vehicle={item}
          distanceMeters={
            location
              ? haversineMeters(location, item.location)
              : null
          }
          onPress={() => router.push(`/tracking/${item.vehicle_id}`)}
        />
        <View style={styles.divider} />
      </View>
    ),
    [location, router],
  );

  return (
    <ScreenShell>
      <View style={styles.container}>
        <View style={styles.mapArea}>
          <TransitMapView
            markers={markers}
            userLocation={location}
            recenterSignal={recenterSignal}
            showUserLocationDot
          />
          <View style={[styles.topChrome, { top: insets.top + spacing.sm }]}>
            <Text style={styles.wordmark}>Karwan e Khizr</Text>
            <TouchableOpacity style={styles.glassButton} activeOpacity={0.7}>
              <Ionicons name="notifications-outline" size={18} color={colors.textPrimary} />
            </TouchableOpacity>
          </View>
          <TouchableOpacity
            style={[styles.searchPill, { top: insets.top + spacing.xl + spacing.base }]}
            activeOpacity={0.85}
            onPress={() => router.push("/plan")}
          >
            <Ionicons name="search" size={18} color={colors.textTertiary} />
            <Text style={styles.searchPlaceholder}>Where are you going?</Text>
            <Ionicons name="mic-outline" size={18} color={colors.textSecondary} />
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.recenterButton, { bottom: (SHEET_SNAP_POINTS[0] as number) + spacing.lg }]}
            activeOpacity={0.8}
            onPress={() => setRecenterSignal((value) => value + 1)}
          >
            <Ionicons name="locate" size={20} color={colors.accent} />
          </TouchableOpacity>
        </View>

        <BottomSheet
          ref={sheetRef}
          index={0}
          snapPoints={SHEET_SNAP_POINTS}
          enableDynamicSizing={false}
          handleIndicatorStyle={styles.handleIndicator}
          backgroundStyle={styles.sheetBackground}
        >
          <View style={styles.sheetHeader}>
            <Text style={styles.sheetTitle}>Nearby Buses</Text>
            {!error && !isLoading && (
              <Text style={styles.sheetCount}>{vehicles.length} running</Text>
            )}
          </View>
          {isLoading ? (
            <StateRow text="Loading live vehicles..." />
          ) : error ? (
            <StateRow text="Can't reach the transit server. Check your connection and try again." />
          ) : vehicles.length === 0 ? (
            <StateRow text="No active buses right now. Vehicles appear here once trips are running." />
          ) : (
            <BottomSheetFlatList
              data={vehicles.slice(0, 10)}
              keyExtractor={(vehicle) => vehicle.vehicle_id}
              renderItem={renderItem}
              contentContainerStyle={{ paddingBottom: spacing.xl }}
            />
          )}
        </BottomSheet>
      </View>
    </ScreenShell>
  );
}

function StateRow({ text }: { text: string }) {
  return (
    <View style={styles.stateWrap}>
      <Text style={styles.stateText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  mapArea: {
    flex: 1,
  },
  topChrome: {
    position: "absolute",
    left: spacing.base,
    right: spacing.base,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  wordmark: {
    ...type.body,
    fontWeight: "700",
    color: colors.textPrimary,
  },
  glassButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "rgba(255,255,255,0.92)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.divider,
    alignItems: "center",
    justifyContent: "center",
  },
  searchPill: {
    position: "absolute",
    left: spacing.base,
    right: spacing.base,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: 999,
    paddingVertical: 14,
    paddingHorizontal: spacing.base,
    shadowColor: "#000000",
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  searchPlaceholder: {
    ...type.body,
    color: colors.textTertiary,
    flex: 1,
  },
  recenterButton: {
    position: "absolute",
    right: spacing.base,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.divider,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000000",
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  },
  sheetBackground: {
    backgroundColor: colors.surface,
  },
  handleIndicator: {
    backgroundColor: colors.divider,
    width: 36,
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
  },
  sheetTitle: {
    ...type.heading,
    color: colors.textPrimary,
  },
  sheetCount: {
    ...type.caption,
    color: colors.textSecondary,
  },
  stateWrap: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  stateText: {
    ...type.caption,
    color: colors.textSecondary,
    lineHeight: 19,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.divider,
    marginHorizontal: spacing.lg,
  },
});
