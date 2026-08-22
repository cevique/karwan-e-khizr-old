export const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { Accept: "application/json", ...init?.headers },
      ...init,
    });
  } catch (cause) {
    throw new Error(`Network request to ${path} failed`, { cause });
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail || response.statusText);
  }
  return (await response.json()) as T;
}

interface ApiDetailEnvelope {
  detail?: unknown;
}

export function describeApiError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    try {
      const parsed = JSON.parse(error.message) as ApiDetailEnvelope;
      if (typeof parsed.detail === "string" && parsed.detail.trim().length > 0) {
        return parsed.detail;
      }
    } catch {
      const raw = error.message.trim();
      if (raw.length > 0 && !raw.startsWith("{")) {
        return raw;
      }
    }
  } else if (error instanceof Error && error.message.length > 0) {
    return fallback;
  }
  return fallback;
}
