// Shared dashboard authentication helper.
//
// The backend (dashboard/auth.py) requires an `X-WB-Token` header on every /api/* route
// except the exempt bootstrap paths (/api/health, /api/session). The token is minted per
// launch and exposed to the same-origin SPA via GET /api/session. This module fetches it
// once, caches the in-flight promise, and attaches it to outgoing requests via `withAuth`.
//
// Both the root API client (src/api.ts) and the V2 client (src/v2/api.ts) import from here
// so the whole app shares ONE token cache and one source of truth for auth.

let tokenPromise: Promise<string> | null = null;

/** Fetch the per-launch dashboard token once and cache the promise. */
export async function ensureToken(): Promise<string> {
  if (!tokenPromise) {
    tokenPromise = fetch("/api/session")
      .then((r) => (r.ok ? r.json() : { token: "" }))
      .then((b: { token?: string }) => b.token ?? "")
      .catch(() => "");
  }

  return tokenPromise;
}

/** Return a RequestInit with the X-WB-Token header set (merging any existing headers). */
export async function withAuth(init?: RequestInit): Promise<RequestInit> {
  const token = await ensureToken();

  if (!token) {
    return init ?? {};
  }

  const headers = new Headers(init?.headers);
  headers.set("X-WB-Token", token);

  return {
    ...init,
    headers,
  };
}
