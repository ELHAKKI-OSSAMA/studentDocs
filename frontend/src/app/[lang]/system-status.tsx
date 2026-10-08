"use client";

import { useEffect, useState } from "react";

type Labels = { title: string; ok: string; down: string };
type State = "loading" | "ok" | "down";

export function SystemStatus({ labels }: { labels: Labels }) {
  const [state, setState] = useState<State>("loading");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/health", { signal: controller.signal, cache: "no-store" })
      .then((res) => setState(res.ok ? "ok" : "down"))
      .catch((err: unknown) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) setState("down");
      });
    return () => controller.abort();
  }, []);

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border p-4 text-sm" role="status">
      <span
        aria-hidden
        className={`size-2.5 rounded-full ${
          state === "ok" ? "bg-success" : state === "down" ? "bg-danger" : "bg-muted animate-pulse"
        }`}
      />
      <span className="font-medium">{labels.title}</span>
      <span className="text-muted">{state === "ok" ? labels.ok : state === "down" ? labels.down : "…"}</span>
    </div>
  );
}
