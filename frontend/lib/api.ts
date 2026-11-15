// The only place the frontend talks to the backend. It never touches the database.

import { clearToken, getToken } from "./auth";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message: string, public code: string, public status: number) {
    super(message);
  }
}

type Options = { method?: string; body?: unknown; auth?: boolean };

export async function api<T>(path: string, { method = "GET", body, auth = false }: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(
      "Can't reach the server. Check that the backend is running, then try again.",
      "NETWORK_ERROR",
      0,
    );
  }

  if (res.status === 204) return undefined as T;

  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && auth) clearToken(); // expired or invalid: force a fresh login
    const message = data?.error?.message ?? "Something went wrong. Please try again.";
    throw new ApiError(message, data?.error?.code ?? "UNKNOWN", res.status);
  }
  return data as T;
}

/** Download a file from an authenticated endpoint (a plain link can't send the token). */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
    .catch(() => {
      throw new ApiError("Can't reach the server. Check that the backend is running, then try again.", "NETWORK_ERROR", 0);
    });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new ApiError(data?.error?.message ?? "Download failed. Please try again.", data?.error?.code ?? "UNKNOWN", res.status);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Public "add to calendar" file for an event. No login needed, so a normal link works. */
export function calendarUrl(slug: string): string {
  return `${API_URL}/public/events/${encodeURIComponent(slug)}/calendar.ics`;
}

export function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : "Something went wrong. Please try again.";
}
