import type { JourneySummaryIn } from "@/services/fares";
import type {
  Coordinates,
  JourneyLegRead,
  JourneyRead,
} from "@/types/api";

export function formatDuration(totalSeconds: number): string {
  const minutes = Math.round(totalSeconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
}

export function legSignature(journey: JourneyRead): string {
  return journey.legs
    .map((leg) =>
      leg.type === "ride" ? `ride:${leg.route.id}` : `walk:${leg.distance_m}`,
    )
    .join("|");
}

export function toJourneySummary(
  journey: JourneyRead,
  origin: Coordinates,
  destination: Coordinates,
): JourneySummaryIn {
  const rideLegs = journey.legs.filter(
    (leg): leg is Extract<JourneyLegRead, { type: "ride" }> => leg.type === "ride",
  );
  return {
    origin_latitude: origin.latitude,
    origin_longitude: origin.longitude,
    destination_latitude: destination.latitude,
    destination_longitude: destination.longitude,
    objective: journey.objective,
    total_duration_s: journey.total_duration_s,
    total_walk_m: journey.total_walk_m,
    transfer_count: journey.transfer_count,
    ride_legs: rideLegs.map((leg) => ({
      route_short_name: leg.route.short_name,
      agency_name: leg.agency.name,
    })),
  };
}

export type JourneyMapLineKind = "ride" | "walk" | "approximate";

export interface JourneyMapLine {
  id: string;
  kind: JourneyMapLineKind;
  coordinates: [number, number][];
}

export function journeyMapLines(journey: JourneyRead): JourneyMapLine[] {
  return journey.legs.flatMap((leg, index): JourneyMapLine[] => {
    if (leg.type === "walk") {
      return [
        {
          id: `walk-${index}`,
          kind: "walk",
          coordinates: [
            [leg.from_location.longitude, leg.from_location.latitude],
            [leg.to_location.longitude, leg.to_location.latitude],
          ],
        },
      ];
    }
    const mapped = leg.route_geometry.coordinates;
    if (mapped && mapped.length > 1) {
      return [{ id: `ride-${index}`, kind: "ride", coordinates: mapped }];
    }
    const board = leg.board_stop.location;
    const alight = leg.alight_stop.location;
    if (!board || !alight) return [];
    return [
      {
        id: `approx-${index}`,
        kind: "approximate",
        coordinates: [
          [board.longitude, board.latitude],
          [alight.longitude, alight.latitude],
        ],
      },
    ];
  });
}
