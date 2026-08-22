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
import { memo, useEffect, useMemo, useRef } from "react";
import { StyleSheet, View } from "react-native";
import { ISLAMABAD_CENTER, MAP_STYLE_URL } from "@/constants/config";
import { colors, radii } from "@/constants/theme";
import type { Coordinates } from "@/types/api";
import { haversineMeters } from "@/utils/geo";
import type { JourneyMapLine } from "@/utils/journey";
import { DemoChip } from "./map/DemoChip";
import { MapErrorBoundary, mapContainerStyle } from "./map/MapFallback";
import {
  buildLineCollection,
  type TransitMapViewProps,
} from "./map/mapTypes";

export type { MapMarker } from "./map/mapTypes";

const FOLLOW_REFLY_MIN_DISTANCE_M = 75;

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
  const collection = buildLineCollection(lines);
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
    <View style={[mapContainerStyle.container, styles.fill]}>
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
      <DemoChip />
    </View>
  );
}

const MemoizedMap = memo(MapLibreInner);

export function TransitMapView(props: TransitMapViewProps) {
  return (
    <MapErrorBoundary>
      <MemoizedMap {...props} />
    </MapErrorBoundary>
  );
}

const styles = StyleSheet.create({
  fill: {
    flex: 1,
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
