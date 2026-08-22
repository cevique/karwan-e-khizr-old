import { Ionicons } from "@expo/vector-icons";
import {
  Camera,
  GeoJSONSource,
  Layer,
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
  useMemo,
  useRef,
} from "react";
import { Platform, StyleSheet, Text, View, type ViewStyle } from "react-native";
import { ISLAMABAD_CENTER, MAP_STYLE_URL } from "@/constants/config";
import { colors, radii, spacing, type } from "@/constants/theme";
import { haversineMeters } from "@/utils/geo";
import type {
  JourneyMapLine,
  JourneyMapLineKind,
} from "@/utils/journey";
import type { Coordinates } from "@/types/api";

const FOLLOW_REFLY_MIN_DISTANCE_M = 75;

export interface MapMarker {
  id: string;
  coordinate: Coordinates;
  kind: "stop" | "vehicle" | "origin" | "destination";
  label?: string;
}

interface TransitMapViewProps {
  markers: MapMarker[];
  userLocation?: Coordinates | null;
  recenterSignal?: number;
  followCoordinate?: Coordinates | null;
  lines?: JourneyMapLine[];
  fitCoordinates?: [number, number][];
  style?: ViewStyle;
  showUserLocationDot?: boolean;
}

interface LineFeature {
  type: "Feature";
  properties: { kind: JourneyMapLineKind };
  geometry: { type: "LineString"; coordinates: [number, number][] };
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

function JourneyLineLayer({
  id,
  lines,
  paint,
}: {
  id: string;
  lines: JourneyMapLine[];
  paint: Record<string, unknown>;
}) {
  if (lines.length === 0) return null;
  const collection = {
    type: "FeatureCollection" as const,
    features: lines.map<LineFeature>((line) => ({
      type: "Feature",
      properties: { kind: line.kind },
      geometry: { type: "LineString", coordinates: line.coordinates },
    })),
  };
  return (
    <>
      <GeoJSONSource id={`${id}-source`} data={collection} />
      <Layer
        id={`${id}-layer`}
        type="line"
        source={`${id}-source`}
        layout={{ "line-cap": "round", "line-join": "round" }}
        paint={paint}
      />
    </>
  );
}

function MapLibreInner({
  markers,
  userLocation,
  recenterSignal,
  followCoordinate,
  lines,
  fitCoordinates,
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

  useEffect(() => {
    if (!fitCoordinates || fitCoordinates.length === 0) return;
    let west = Infinity;
    let south = Infinity;
    let east = -Infinity;
    let north = -Infinity;
    for (const [lng, lat] of fitCoordinates) {
      west = Math.min(west, lng);
      east = Math.max(east, lng);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
    }
    if (west === east && south === north) {
      cameraRef.current?.flyTo({ center: [west, south], zoom: 15, duration: 600 });
      return;
    }
    cameraRef.current?.fitBounds([west, south, east, north], {
      padding: { top: 90, right: 50, bottom: 110, left: 50 },
      duration: 600,
    });
  }, [fitCoordinates]);

  const initialCenter: [number, number] = userLocation
    ? [userLocation.longitude, userLocation.latitude]
    : ISLAMABAD_CENTER;

  const rideLines = useMemo(
    () => (lines ?? []).filter((line) => line.kind === "ride"),
    [lines],
  );
  const walkLines = useMemo(
    () => (lines ?? []).filter((line) => line.kind === "walk"),
    [lines],
  );
  const approximateLines = useMemo(
    () => (lines ?? []).filter((line) => line.kind === "approximate"),
    [lines],
  );

  return (
    <View style={styles.container}>
      <Map mapStyle={MAP_STYLE_URL} style={StyleSheet.absoluteFill}>
        <Camera
          ref={cameraRef}
          initialViewState={{ center: initialCenter, zoom: 13 }}
        />
        <JourneyLineLayer
          id="journey-approximate"
          lines={approximateLines}
          paint={{
            "line-color": colors.textTertiary,
            "line-width": 2,
            "line-dasharray": [1.5, 1.5],
          }}
        />
        <JourneyLineLayer
          id="journey-walk"
          lines={walkLines}
          paint={{
            "line-color": colors.textSecondary,
            "line-width": 2,
            "line-dasharray": [2, 2],
          }}
        />
        <JourneyLineLayer
          id="journey-ride"
          lines={rideLines}
          paint={{ "line-color": colors.accent, "line-width": 3 }}
        />
        {showUserLocationDot ? <UserLocation /> : null}
        {markers.map((marker) => (
          <ViewAnnotation
            key={`${marker.kind}-${marker.id}`}
            id={`${marker.kind}-${marker.id}`}
            lngLat={[marker.coordinate.longitude, marker.coordinate.latitude]}
          >
            <View
              style={
                marker.kind === "vehicle"
                  ? styles.vehiclePin
                  : marker.kind === "origin"
                    ? styles.originDot
                    : marker.kind === "destination"
                      ? styles.destinationDot
                      : styles.stopDot
              }
            >
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
  originDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: colors.surface,
    borderWidth: 3,
    borderColor: colors.accent,
  },
  destinationDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: colors.textPrimary,
    borderWidth: 3,
    borderColor: colors.surface,
  },
});
