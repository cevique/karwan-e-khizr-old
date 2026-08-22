import type { ViewStyle } from "react-native";
import type { Coordinates } from "@/types/api";
import type { JourneyMapLine, JourneyMapLineKind } from "@/utils/journey";

export interface MapMarker {
  id: string;
  coordinate: Coordinates;
  kind: "stop" | "vehicle" | "origin" | "destination";
  label?: string;
}

export interface TransitMapViewProps {
  markers: MapMarker[];
  userLocation?: Coordinates | null;
  recenterSignal?: number;
  followCoordinate?: Coordinates | null;
  lines?: JourneyMapLine[];
  fitCoordinates?: [number, number][];
  style?: ViewStyle;
  showUserLocationDot?: boolean;
}

export interface LineFeature {
  type: "Feature";
  properties: { kind: JourneyMapLineKind };
  geometry: { type: "LineString"; coordinates: [number, number][] };
}

export function buildLineCollection(lines: JourneyMapLine[]) {
  return {
    type: "FeatureCollection" as const,
    features: lines.map<LineFeature>((line) => ({
      type: "Feature",
      properties: { kind: line.kind },
      geometry: { type: "LineString", coordinates: line.coordinates },
    })),
  };
}
