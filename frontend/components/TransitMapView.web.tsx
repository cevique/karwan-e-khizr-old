import { memo, useEffect, useRef, useState, type CSSProperties } from "react";
import { StyleSheet, View } from "react-native";
import {
  Map as MapLibreMap,
  Marker as MapLibreMarker,
  NavigationControl,
  type LineLayerSpecification,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { ISLAMABAD_CENTER, MAP_STYLE_URL } from "@/constants/config";
import type { Coordinates } from "@/types/api";
import { haversineMeters } from "@/utils/geo";
import type { JourneyMapLine } from "@/utils/journey";
import { DemoChip } from "./map/DemoChip";
import { MapErrorBoundary, mapContainerStyle } from "./map/MapFallback";
import {
  buildLineCollection,
  type MapMarker,
  type TransitMapViewProps,
} from "./map/mapTypes";

export type { MapMarker } from "./map/mapTypes";

const FOLLOW_REFLY_MIN_DISTANCE_M = 75;

interface LineSpec {
  key: string;
  kind: JourneyMapLine["kind"];
  paint: LineLayerSpecification["paint"];
}

const LINE_SPECS: LineSpec[] = [
  {
    key: "journey-approximate",
    kind: "approximate",
    paint: {
      "line-color": "#9CA3AF",
      "line-width": 2,
      "line-dasharray": [1.5, 1.5],
    },
  },
  {
    key: "journey-walk",
    kind: "walk",
    paint: {
      "line-color": "#6B7280",
      "line-width": 2,
      "line-dasharray": [2, 2],
    },
  },
  {
    key: "journey-ride",
    kind: "ride",
    paint: { "line-color": "#0A6E64", "line-width": 3 },
  },
];

function applyJourneyLines(map: MapLibreMap, lines: JourneyMapLine[]) {
  for (const spec of LINE_SPECS) {
    const layerId = `${spec.key}-layer`;
    const sourceId = `${spec.key}-source`;
    if (map.getLayer(layerId)) map.removeLayer(layerId);
    if (map.getSource(sourceId)) map.removeSource(sourceId);
    const matching = lines.filter((line) => line.kind === spec.kind);
    if (matching.length === 0) continue;
    map.addSource(sourceId, {
      type: "geojson",
      data: buildLineCollection(matching),
    });
    map.addLayer({
      id: layerId,
      type: "line",
      source: sourceId,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: spec.paint,
    });
  }
}

const BUS_SVG =
  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">' +
  '<rect x="5" y="2" width="14" height="17" rx="3" stroke="#FFFFFF" stroke-width="2"/>' +
  '<path d="M5 9H19" stroke="#FFFFFF" stroke-width="2"/>' +
  '<circle cx="9" cy="15.5" r="1.3" fill="#FFFFFF"/>' +
  '<circle cx="15" cy="15.5" r="1.3" fill="#FFFFFF"/>' +
  '<path d="M8 22L9 19M16 22L15 19" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round"/>' +
  "</svg>";

function markerElement(kind: MapMarker["kind"]): HTMLDivElement {
  const el = document.createElement("div");
  switch (kind) {
    case "vehicle":
      el.style.cssText =
        "display:flex;align-items:center;justify-content:center;" +
        "width:22px;height:22px;border-radius:8px;background:#0A6E64;" +
        "border:2px solid #FFFFFF;box-shadow:0 2px 6px rgba(0,0,0,0.25);";
      el.innerHTML = BUS_SVG;
      break;
    case "stop":
      el.style.cssText =
        "width:12px;height:12px;border-radius:6px;background:#FFFFFF;" +
        "border:2px solid #14181C;";
      break;
    case "origin":
      el.style.cssText =
        "width:14px;height:14px;border-radius:7px;background:#FFFFFF;" +
        "border:3px solid #0A6E64;";
      break;
    case "destination":
      el.style.cssText =
        "width:14px;height:14px;border-radius:7px;background:#14181C;" +
        "border:3px solid #FFFFFF;";
      break;
  }
  return el;
}

function userDotElement(): HTMLDivElement {
  const el = document.createElement("div");
  el.style.cssText =
    "width:16px;height:16px;border-radius:50%;background:#1E88E5;" +
    "border:3px solid #FFFFFF;box-shadow:0 0 0 2px rgba(30,136,229,0.25);";
  return el;
}

const CANVAS_STYLE: CSSProperties = {
  position: "absolute",
  top: 0,
  right: 0,
  bottom: 0,
  left: 0,
};

function MapLibreWebInner({
  markers,
  userLocation,
  recenterSignal,
  followCoordinate,
  lines,
  fitCoordinates,
  showUserLocationDot,
  style,
}: TransitMapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const initialLocationRef = useRef(userLocation);
  const [ready, setReady] = useState(false);

  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef(new Map<string, MapLibreMarker>());
  const userDotRef = useRef<MapLibreMarker | null>(null);
  const lastFollowedRef = useRef<Coordinates | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const markerRegistry = markersRef.current;
    const initial = initialLocationRef.current;
    const map = new MapLibreMap({
      container,
      style: MAP_STYLE_URL,
      center: initial
        ? [initial.longitude, initial.latitude]
        : ISLAMABAD_CENTER,
      zoom: 13,
    });
    map.addControl(
      new NavigationControl({ showCompass: false }),
      "top-right",
    );
    map.on("load", () => setReady(true));
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      markerRegistry.clear();
      userDotRef.current = null;
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    applyJourneyLines(map, lines ?? []);
  }, [lines, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const nextKeys = new Set<string>();
    for (const marker of markers) {
      const key = `${marker.kind}-${marker.id}`;
      nextKeys.add(key);
      const lngLat: [number, number] = [
        marker.coordinate.longitude,
        marker.coordinate.latitude,
      ];
      const existing = markersRef.current.get(key);
      if (existing) {
        existing.setLngLat(lngLat);
      } else {
        markersRef.current.set(
          key,
          new MapLibreMarker({
            element: markerElement(marker.kind),
            anchor: "center",
          })
            .setLngLat(lngLat)
            .addTo(map),
        );
      }
    }
    for (const [key, existing] of Array.from(markersRef.current.entries())) {
      if (!nextKeys.has(key)) {
        existing.remove();
        markersRef.current.delete(key);
      }
    }
  }, [markers, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (!showUserLocationDot || !userLocation) {
      userDotRef.current?.remove();
      userDotRef.current = null;
      return;
    }
    const lngLat: [number, number] = [
      userLocation.longitude,
      userLocation.latitude,
    ];
    if (!userDotRef.current) {
      userDotRef.current = new MapLibreMarker({
        element: userDotElement(),
        anchor: "center",
      })
        .setLngLat(lngLat)
        .addTo(map);
    } else {
      userDotRef.current.setLngLat(lngLat);
    }
  }, [showUserLocationDot, userLocation, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (recenterSignal && userLocation) {
      lastFollowedRef.current = null;
      map.flyTo({
        center: [userLocation.longitude, userLocation.latitude],
        zoom: 14,
        duration: 600,
      });
    }
  }, [recenterSignal]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !followCoordinate) return;
    const last = lastFollowedRef.current;
    if (
      last &&
      haversineMeters(last, followCoordinate) < FOLLOW_REFLY_MIN_DISTANCE_M
    ) {
      return;
    }
    lastFollowedRef.current = followCoordinate;
    map.flyTo({
      center: [followCoordinate.longitude, followCoordinate.latitude],
      zoom: 15,
      duration: 600,
    });
  }, [followCoordinate]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !fitCoordinates || fitCoordinates.length === 0) return;
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
      map.flyTo({ center: [west, south], zoom: 15, duration: 600 });
      return;
    }
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      {
        padding: { top: 90, right: 50, bottom: 110, left: 50 },
        duration: 600,
      },
    );
  }, [fitCoordinates]);

  return (
    <View style={[mapContainerStyle.container, styles.relative, style]}>
      <div ref={containerRef} style={CANVAS_STYLE} />
      <DemoChip />
    </View>
  );
}

const MemoizedMap = memo(MapLibreWebInner);

export function TransitMapView(props: TransitMapViewProps) {
  return (
    <MapErrorBoundary>
      <MemoizedMap {...props} />
    </MapErrorBoundary>
  );
}

const styles = StyleSheet.create({
  relative: {
    position: "relative",
  },
});
