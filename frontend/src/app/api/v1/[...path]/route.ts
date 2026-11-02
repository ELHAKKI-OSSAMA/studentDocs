/**
 * Same-origin API proxy: /api/v1/* is forwarded to the FastAPI backend, so session cookies and the CSRF
 * double-submit keep working on a single public domain (serverless deployment: the backend is a separate
 * Vercel project). The Docker stack never reaches this route: Caddy sends /api to the backend directly.
 *
 * Server-only settings: BACKEND_URL (backend origin) and PROXY_SHARED_SECRET (the backend refuses any call
 * without it, so the client-IP header below cannot be forged by calling the backend directly).
 */
import type { NextRequest } from "next/server";

const BACKEND = (
  process.env.BACKEND_URL ??
  process.env.BACKEND_INTERNAL_URL ??
  "http://localhost:8000"
).replace(/\/$/, "");
// Hop-by-hop headers, and those the runtime recomputes (fetch already decoded the body).
const DROP_REQUEST = new Set([
  "host",
  "connection",
  "content-length",
  "x-studentdocs-proxy-secret",
  "x-studentdocs-client-ip",
]);
const DROP_RESPONSE = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "transfer-encoding",
]);

/** Client IP as set by the platform edge (Vercel overwrites these headers; the first entry is the client). */
function clientIp(request: NextRequest): string {
  const forwarded = request.headers
    .get("x-forwarded-for")
    ?.split(",")[0]
    ?.trim();
  return request.headers.get("x-real-ip") ?? forwarded ?? "";
}

async function forward(request: NextRequest): Promise<Response> {
  const url = new URL(request.url);
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!DROP_REQUEST.has(key.toLowerCase())) headers.set(key, value);
  });
  const secret = process.env.PROXY_SHARED_SECRET;
  if (secret) headers.set("x-studentdocs-proxy-secret", secret);
  headers.set("x-studentdocs-client-ip", clientIp(request));

  const hasBody = !["GET", "HEAD"].includes(request.method);
  const upstream = await fetch(`${BACKEND}${url.pathname}${url.search}`, {
    method: request.method,
    headers,
    body: hasBody ? request.body : undefined,
    redirect: "manual",
    cache: "no-store",
    // Streams the upload instead of buffering it (required by Node's fetch for a stream body).
    ...(hasBody ? { duplex: "half" } : {}),
  } as RequestInit);

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (
      !DROP_RESPONSE.has(key.toLowerCase()) &&
      key.toLowerCase() !== "set-cookie"
    )
      responseHeaders.set(key, value);
  });
  // Several cookies (access, refresh, CSRF): each Set-Cookie must be kept as its own header.
  for (const cookie of upstream.headers.getSetCookie())
    responseHeaders.append("set-cookie", cookie);
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
