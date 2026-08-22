import { DEMO_MODE } from "@/constants/config";
import { demoJourneySearch } from "@/mocks/demoData";
import { fetchJson } from "./api";
import type { JourneySearchRequest, JourneySearchResponse } from "@/types/api";

export function searchJourneys(
  request: JourneySearchRequest,
): Promise<JourneySearchResponse> {
  if (DEMO_MODE) {
    return Promise.resolve(demoJourneySearch(request));
  }
  return fetchJson("/api/transit/journeys/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
