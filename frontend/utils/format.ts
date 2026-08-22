/**
 * Utility functions for formatting transit data (durations, distances, times)
 */

export function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.round(seconds)} sec`;
  }
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes} min`;
  }
  const hours = Math.floor(minutes / 60);
  const remainingMins = minutes % 60;
  if (remainingMins === 0) {
    return `${hours} hr`;
  }
  return `${hours} hr ${remainingMins} min`;
}

export function formatDistance(meters: number): string {
  if (meters < 1000) {
    return `${Math.round(meters)} m`;
  }
  const km = (meters / 1000).toFixed(1);
  return `${km} km`;
}

export function formatSpeed(speedKmh: number | null): string {
  if (speedKmh === null || speedKmh === undefined) return "-- km/h";
  return `${Math.round(speedKmh)} km/h`;
}

export function formatETA(minutes: number): string {
  if (minutes <= 0) return "Due";
  if (minutes === 1) return "1 min";
  return `${minutes} min`;
}

export function formatFare(pkr: number): string {
  return `PKR ${pkr.toFixed(2)}`;
}
