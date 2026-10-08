const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

/** Reports frontend liveness plus backend readiness (no internal details are exposed). */
export async function GET() {
  try {
    const res = await fetch(`${backendUrl}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    return Response.json({ frontend: "ok", backend: res.ok ? "ok" : "down" }, { status: res.ok ? 200 : 503 });
  } catch {
    return Response.json({ frontend: "ok", backend: "down" }, { status: 503 });
  }
}
