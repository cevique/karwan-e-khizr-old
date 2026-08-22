import { fetchJson } from "./api";
import type { JourneySearchRequest, JourneySearchResponse } from "@/types/api";

export function searchJourneys(
  request: JourneySearchRequest,
): Promise<JourneySearchResponse> {
  return fetchJson("/api/transit/journeys/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
