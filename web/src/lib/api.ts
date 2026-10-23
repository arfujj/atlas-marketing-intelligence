import "server-only";

import type { components } from "./api-schema";

export type OptimizeRequest = components["schemas"]["OptimizeRequest"];

export const API_URL = process.env.ATLAS_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Server-side GET against the ATLAS API. Responses are not cached: the API serves
 *  read-only stored runs, and freshness matters more than a few ms. */
export async function api<T>(path: string, params?: Record<string, string | string[] | undefined>): Promise<T> {
  const url = new URL(path, API_URL);
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v === undefined || v === "") continue;
    for (const x of Array.isArray(v) ? v : [v]) url.searchParams.append(k, x);
  }
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, typeof body.detail === "string" ? body.detail : res.statusText);
  }
  return res.json() as Promise<T>;
}
