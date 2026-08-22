const HAS_OFFSET_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/i;

export function parseApiTimestamp(
  isoTimestamp: string | null | undefined,
): Date | null {
  if (!isoTimestamp) return null;
  const normalized = HAS_OFFSET_PATTERN.test(isoTimestamp)
    ? isoTimestamp
    : `${isoTimestamp}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function etaMinutes(
  isoTimestamp: string | null | undefined,
): number | null {
  const target = parseApiTimestamp(isoTimestamp);
  if (!target) return null;
  const diffMs = target.getTime() - Date.now();
  return Math.max(0, Math.round(diffMs / 60_000));
}
