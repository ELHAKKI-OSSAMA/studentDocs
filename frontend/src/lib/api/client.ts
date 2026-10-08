/**
 * Browser API client. Same-origin calls to /api/v1 (routed to the backend by the entry proxy).
 * - Session cookies are httpOnly; the CSRF token is read from its cookie and echoed in a header.
 * - On 401 the client refreshes the session once (single-flight) and retries the request.
 * - A FormData body is sent as multipart (the browser sets the boundary); anything else as JSON.
 */

export const API_BASE = "/api/v1";
const CSRF_COOKIE = "sd_csrf";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

type RequestOptions = {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  /** Do not try to refresh the session on 401 (auth endpoints). */
  noRefresh?: boolean;
};

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function rawFetch(path: string, opts: RequestOptions): Promise<Response> {
  const method = (opts.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
  if (opts.body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method)) {
    const csrf = readCookie(CSRF_COOKIE);
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  try {
    return await fetch(buildUrl(path, opts.query), {
      method,
      headers,
      body: isForm ? (opts.body as FormData) : opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network", "Network error");
  }
}

let refreshInFlight: Promise<boolean> | null = null;

/** Rotates the session. Concurrent callers share one request (avoids refresh-token reuse detection). */
export function refreshSession(): Promise<boolean> {
  refreshInFlight ??= rawFetch("/auth/refresh", { method: "POST" })
    .then((res) => res.ok)
    .catch(() => false)
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
}

async function toError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    const err = body?.error;
    if (err?.code) return new ApiError(res.status, err.code, err.message ?? "", err.details ?? null);
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, "generic", res.statusText);
}

async function send(path: string, opts: RequestOptions): Promise<Response> {
  let res = await rawFetch(path, opts);
  if (res.status === 401 && !opts.noRefresh && !path.startsWith("/auth/refresh")) {
    if (await refreshSession()) res = await rawFetch(path, opts);
  }
  if (!res.ok) throw await toError(res);
  return res;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await send(path, opts);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Filename from a Content-Disposition header (RFC 5987 `filename*` first). */
export function dispositionFilename(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      /* malformed: fall through */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : fallback;
}

/**
 * Downloads a file through an authorized backend endpoint (never a direct storage URL):
 * fetch with the session cookies, then save the blob under the server-provided name.
 */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await send(path, {});
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = dispositionFilename(res.headers.get("Content-Disposition"), fallbackName);
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
