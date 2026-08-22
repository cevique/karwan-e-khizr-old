import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Easing,
  Share,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Button } from "@/components/ui/Button";
import { RouteCircle } from "@/components/ui/RouteCircle";
import { TransitMapView, type MapMarker } from "@/components/TransitMapView";
import { DEFAULT_REALTIME_POLL_INTERVAL_MS } from "@/constants/config";
import { colors, elevation, radii, spacing, type } from "@/constants/theme";
import { listActiveVehicles, getVehicleEta } from "@/services/realtime";
import { getRoute } from "@/services/transit";
import type { RouteDetail, VehicleETAList, VehiclePositionRead } from "@/types/api";
import { etaMinutes } from "@/utils/time";

const ARRIVING_SOON_MIN = 5;

export default function TrackingScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { vehicleId } = useLocalSearchParams<{ vehicleId: string }>();
  const [vehicle, setVehicle] = useState<VehiclePositionRead | null>(null);
  const [etas, setEtas] = useState<VehicleETAList | null>(null);
  const [route, setRoute] = useState<RouteDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pulse = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (!vehicleId) return;
    let cancelled = false;

    const tick = async () => {
      try {
        const [vehicles, etaData] = await Promise.all([
          listActiveVehicles(),
          getVehicleEta(vehicleId),
        ]);
        if (cancelled) return;
        const match = vehicles.find((v) => v.vehicle_id === vehicleId) ?? null;
        setVehicle(match);
        setEtas(etaData);
        setError(match ? null : "This vehicle is no longer running.");
      } catch {
        if (!cancelled) setError("Lost connection to the transit server.");
      }
    };

    void tick();
    const interval = setInterval(tick, DEFAULT_REALTIME_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [vehicleId]);

  useEffect(() => {
    if (!vehicle?.route_id || route) return;
    let cancelled = false;
    getRoute(vehicle.route_id)
      .then((data) => {
        if (!cancelled) setRoute(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [vehicle?.route_id, route]);

  const arrivingSoon = useMemo(() => {
    const minutes = vehicle ? etaMinutes(vehicle.estimated_arrival_next_stop) : null;
    return minutes !== null && minutes < ARRIVING_SOON_MIN;
  }, [vehicle]);

  useEffect(() => {
    if (!arrivingSoon) {
      pulse.stopAnimation();
      pulse.setValue(1);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 0.35,
          duration: 700,
          easing: Easing.out(Easing.quad),
          useNativeDriver: true,
        }),
        Animated.timing(pulse, {
          toValue: 1,
          duration: 700,
          easing: Easing.out(Easing.quad),
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [arrivingSoon]);

  const markers = useMemo<MapMarker[]>(
    () =>
      vehicle
        ? [{ id: vehicle.vehicle_id, coordinate: vehicle.location, kind: "vehicle" }]
        : [],
    [vehicle],
  );

  const nextStopEta = useMemo(() => {
    if (!etas || !vehicle?.next_stop_id) return null;
    return (
      etas.etas.find((eta) => eta.stop_id === vehicle.next_stop_id) ??
      etas.etas[0] ??
      null
    );
  }, [etas, vehicle]);

  const share = () => {
    void Share.share({
      message: vehicle
        ? `Track bus ${vehicle.route_short_name ?? ""} live on Karwan e Khizr (vehicle ${vehicle.vehicle_id})`
        : "Karwan e Khizr live bus tracking",
    });
  };

  return (
    <View style={styles.container}>
      <TransitMapView markers={markers} userLocation={null} />

      <TouchableOpacity
        style={[styles.backButton, { top: insets.top + spacing.md }]}
        onPress={() => router.back()}
      >
        <Ionicons name="chevron-back" size={20} color={colors.textPrimary} />
      </TouchableOpacity>

      <View
        style={[
          styles.arrivalPillWrap,
          { top: insets.top + spacing.md },
        ]}
        pointerEvents="none"
      >
        {vehicle && !error && (
          <View style={[styles.arrivalPill, arrivingSoon && styles.arrivalPillLive]}>
            <Animated.View
              style={[styles.pulseDot, { opacity: pulse }, arrivingSoon && styles.pulseDotLive]}
            />
            <View>
              <Text style={styles.arrivalLabel}>
                {arrivingSoon ? "Arriving soon at" : "Next stop"}
              </Text>
              <Text style={styles.arrivalValue}>
                {vehicle.next_stop_name ?? "--"}
              </Text>
            </View>
          </View>
        )}
        {error && (
          <View style={styles.arrivalPill}>
            <Text style={styles.arrivalLabel}>{error}</Text>
          </View>
        )}
      </View>

      <View
        style={[styles.sheet, { paddingBottom: insets.bottom + spacing.base }]}
      >
        <View style={styles.routeRow}>
          {vehicle?.route_short_name ? (
            <RouteCircle label={vehicle.route_short_name} size={44} />
          ) : (
            <Ionicons name="bus-outline" size={28} color={colors.textSecondary} />
          )}
          <View style={styles.routeInfo}>
            <Text style={styles.routeName} numberOfLines={1}>
              {route?.long_name ?? vehicle?.route_short_name ?? "Bus"}
            </Text>
            <Text style={styles.routeMeta}>
              {nextStopEta
                ? `${Math.max(0, Math.round((new Date(nextStopEta.estimated_arrival).getTime() - Date.now()) / 60000))} min away · ${vehicle?.speed_kmh !== null && vehicle?.speed_kmh !== undefined ? `${Math.round(vehicle.speed_kmh)} km/h` : "live"}`
                : "Waiting for live data..."}
            </Text>
          </View>
        </View>
        <View style={styles.actionsRow}>
          <Button label="Book" variant="filled" onPress={() => {}} disabled style={{ flex: 1 }} />
          <Button label="Share" variant="ghost" onPress={share} style={{ flex: 1 }} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.bgPrimary,
  },
  backButton: {
    position: "absolute",
    left: spacing.base,
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.surface,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.divider,
    alignItems: "center",
    justifyContent: "center",
    ...elevation.soft,
  },
  arrivalPillWrap: {
    position: "absolute",
    left: spacing.xl + spacing.lg,
    right: spacing.base,
    alignItems: "flex-end",
  },
  arrivalPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.divider,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    ...elevation.soft,
  },
  arrivalPillLive: {
    borderColor: colors.warningLive,
  },
  pulseDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.textTertiary,
  },
  pulseDotLive: {
    backgroundColor: colors.warningLive,
  },
  arrivalLabel: {
    ...type.micro,
    color: colors.textSecondary,
  },
  arrivalValue: {
    ...type.heading,
    color: colors.textPrimary,
  },
  sheet: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.surface,
    borderTopLeftRadius: radii.card + 6,
    borderTopRightRadius: radii.card + 6,
    paddingTop: spacing.base,
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
    ...elevation.soft,
  },
  routeRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.base,
  },
  routeInfo: {
    flex: 1,
  },
  routeName: {
    ...type.heading,
    color: colors.textPrimary,
  },
  routeMeta: {
    ...type.caption,
    color: colors.textSecondary,
    marginTop: 2,
  },
  actionsRow: {
    flexDirection: "row",
    gap: spacing.md,
  },
});
