import { JourneySearchRequest, JourneySearchResponse, JourneyRead } from "../types";
import { apiRequest } from "./api";
import { DEMO_MODE } from "../constants/config";
import { MOCK_JOURNEYS } from "../mocks";

export async function searchJourneys(
  request: JourneySearchRequest
): Promise<JourneyRead[]> {
  if (DEMO_MODE) {
    return MOCK_JOURNEYS;
  }
  try {
    const response = await apiRequest<JourneySearchResponse>(
      "/api/transit/journeys/search",
      {
        method: "POST",
        body: JSON.stringify(request),
      }
    );
    return response.journeys || [];
  } catch (e) {
    console.warn("Journey search API failed, using mock journey results:", e);
    return MOCK_JOURNEYS;
  }
}
