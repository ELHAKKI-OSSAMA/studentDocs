"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./client";
import type { Me } from "./types";

export const meKey = ["auth", "me"] as const;

export function useMe() {
  return useQuery<Me, ApiError>({
    queryKey: meKey,
    queryFn: () => api<Me>("/auth/me"),
    retry: false,
    staleTime: 60_000,
  });
}

export function useHasPermission(permission: string): boolean {
  const { data } = useMe();
  return !!data?.permissions.includes(permission);
}

/** GET a resource; keys are derived from the path + query so mutations can invalidate by prefix. */
export function useApiQuery<T>(
  path: string,
  query?: Record<string, string | number | undefined>,
  options: {
    enabled?: boolean;
    /** Milliseconds, or a function of the latest data (e.g. poll only while a scan is running). */
    refetchInterval?: number | ((data: T | undefined) => number | false);
  } = {},
) {
  const interval = options.refetchInterval;
  return useQuery<T, ApiError>({
    queryKey: ["api", path, query ?? {}],
    queryFn: () => api<T>(path, { query }),
    enabled: options.enabled ?? true,
    refetchInterval: typeof interval === "function" ? (q) => interval(q.state.data) : interval,
  });
}

/** Mutation that invalidates every query whose path starts with one of `invalidate`. */
export function useApiMutation<TBody, TResult = unknown>(
  build: (body: TBody) => { path: string; method: string; body?: unknown },
  invalidate: string[],
) {
  const qc = useQueryClient();
  return useMutation<TResult, ApiError, TBody>({
    mutationFn: (input) => {
      const { path, method, body } = build(input);
      return api<TResult>(path, { method, body });
    },
    onSuccess: () =>
      Promise.all(
        invalidate.map((prefix) =>
          qc.invalidateQueries({
            predicate: (q) => q.queryKey[0] === "api" && String(q.queryKey[1]).startsWith(prefix),
          }),
        ),
      ),
  });
}

/** Returns a function invalidating every API query whose path starts with one of the prefixes. */
export function useInvalidate() {
  const qc = useQueryClient();
  return useCallback(
    (prefixes: string[]) =>
      qc.invalidateQueries({
        predicate: (q) => q.queryKey[0] === "api" && prefixes.some((p) => String(q.queryKey[1]).startsWith(p)),
      }),
    [qc],
  );
}
