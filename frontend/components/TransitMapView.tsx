import { Ionicons } from "@expo/vector-icons";
import {
  Camera,
  Map,
  UserLocation,
  ViewAnnotation,
  type CameraRef,
} from "@maplibre/maplibre-react-native";
import {
  Component,
  memo,
  ReactNode,
  useEffect,
  useRef,
} from "react";
import { Platform, StyleSheet, Text, View, type ViewStyle } from "react-native";
import { ISLAMABAD_CENTER, MAP_STYLE_URL } from "@/constants/config";
import { colors, radii, spacing, type } from "@/constants/theme";
import { haversineMeters } from "@/utils/geo";
import type { Coordinates } from "@/types/api";

const FOLLOW_REFLY_MIN_DISTANCE_M = 75;

export interface MapMarker {
  id: string;
  coordinate: Coordinates;
  kind: "stop" | "vehicle";
  label?: string;
}

interface TransitMapViewProps {
  markers: MapMarker[];
  userLocation?: Coordinates | null;
  recenterSignal?: number;
  followCoordinate?: Coordinates | null;
  style?: ViewStyle;
  showUserLocationDot?: boolean;
}

class MapErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed) return <MapFallback />;
    return this.props.children;
  }
}

function MapFallback() {
  return (
    <View style={[styles.container, styles.fallback]}>
      <Ionicons name="map-outline" size={24} color={colors.textSecondary} />
      <Text style={styles.fallbackTitle}>Map unavailable here</Text>
      <Text style={styles.fallbackBody}>
        The live map needs the development build. Nearby buses are listed below.
      </Text>
    </View>
  );
}

function MapLibreInner({
  markers,
  userLocation,
  recenterSignal,
  followCoordinate,
  showUserLocationDot,
}: TransitMapViewProps) {
  const cameraRef = useRef<CameraRef>(null);
  const lastFollowedRef = useRef<Coordinates | null>(null);

  useEffect(() => {
    if (recenterSignal && userLocation) {
      lastFollowedRef.current = null;
      cameraRef.current?.flyTo({
        center: [userLocation.longitude, userLocation.latitude],
        zoom: 14,
        duration: 600,
      });
    }
  }, [recenterSignal]);

  useEffect(() => {
    if (!followCoordinate) return;
    const last = lastFollowedRef.current;
    if (
      last &&
      haversineMeters(last, followCoordinate) < FOLLOW_REFLY_MIN_DISTANCE_M
    ) {
      return;
    }
    lastFollowedRef.current = followCoordinate;
    cameraRef.current?.flyTo({
      center: [followCoordinate.longitude, followCoordinate.latitude],
      zoom: 15,
      duration: 600,
    });
  }, [followCoordinate]);

  const initialCenter: [number, number] = userLocation
    ? [userLocation.longitude, userLocation.latitude]
    : ISLAMABAD_CENTER;

  return (
    <View style={styles.container}>
      <Map mapStyle={MAP_STYLE_URL} style={StyleSheet.absoluteFill}>
        <Camera
          ref={cameraRef}
          initialViewState={{ center: initialCenter, zoom: 13 }}
        />
        {showUserLocationDot ? <UserLocation /> : null}
        {markers.map((marker) => (
          <ViewAnnotation
            key={`${marker.kind}-${marker.id}`}
            id={`${marker.kind}-${marker.id}`}
            lngLat={[marker.coordinate.longitude, marker.coordinate.latitude]}
          >
            <View style={marker.kind === "vehicle" ? styles.vehiclePin : styles.stopDot}>
              {marker.kind === "vehicle" && (
                <Ionicons name="bus" size={12} color={colors.surface} />
              )}
            </View>
          </ViewAnnotation>
        ))}
      </Map>
    </View>
  );
}

const MemoizedMap = memo(MapLibreInner);

export function TransitMapView(props: TransitMapViewProps) {
  if (Platform.OS === "web") {
    return <MapFallback />;
  }
  return (
    <MapErrorBoundary>
      <MemoizedMap {...props} />
    </MapErrorBoundary>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#E8EAE6",
    overflow: "hidden",
  },
  fallback: {
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.sm,
    padding: spacing.xl,
  },
  fallbackTitle: {
    ...type.heading,
    color: colors.textPrimary,
  },
  fallbackBody: {
    ...type.caption,
    color: colors.textSecondary,
    textAlign: "center",
  },
  vehiclePin: {
    width: 22,
    height: 22,
    borderRadius: radii.button - 4,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 2,
    borderColor: colors.surface,
  },
  stopDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.surface,
    borderWidth: 2,
    borderColor: colors.textPrimary,
  },
});
