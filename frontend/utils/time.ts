export function etaMinutes(isoTimestamp: string | null | undefined): number | null {
  if (!isoTimestamp) return null;
  const target = new Date(isoTimestamp).getTime();
  if (Number.isNaN(target)) return null;
  const diffMs = target - Date.now();
  return Math.max(0, Math.round(diffMs / 60_000));
}
