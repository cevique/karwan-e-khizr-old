import { fetchJson } from "./api";
import type { RoutingObjective } from "@/types/api";

export interface RideLegSummaryIn {
  route_short_name: string;
  agency_name: string;
}

export interface JourneySummaryIn {
  origin_latitude: number;
  origin_longitude: number;
  destination_latitude: number;
  destination_longitude: number;
  objective: RoutingObjective;
  total_duration_s: number;
  total_walk_m: number;
  transfer_count: number;
  ride_legs: RideLegSummaryIn[];
}

export interface FareQuoteResponse {
  amount: string;
  currency: string;
  ride_leg_count: number;
  fare_rule_name: string;
}

export function quoteJourney(
  journey: JourneySummaryIn,
): Promise<FareQuoteResponse> {
  return fetchJson("/api/fares/quote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(journey),
  });
}
