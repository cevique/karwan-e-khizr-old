import { useState, useCallback } from "react";
import { JourneyRead, JourneySearchRequest } from "../types";
import { searchJourneys } from "../services/journeyService";

export interface UseJourneySearchResult {
  journeys: JourneyRead[];
  loading: boolean;
  error: string | null;
  executeSearch: (request: JourneySearchRequest) => Promise<JourneyRead[]>;
}

export function useJourneySearch(): UseJourneySearchResult {
  const [journeys, setJourneys] = useState<JourneyRead[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const executeSearch = useCallback(async (request: JourneySearchRequest) => {
    setLoading(true);
    setError(null);
    try {
      const results = await searchJourneys(request);
      setJourneys(results);
      return results;
    } catch (e: any) {
      setError(e.message || "Failed to search journeys");
      setJourneys([]);
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  return {
    journeys,
    loading,
    error,
    executeSearch,
  };
}
