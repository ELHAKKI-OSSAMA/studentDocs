"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/i18n/client";
import { useMe } from "@/lib/api/hooks";
import type { Me } from "@/lib/api/types";

export type Area = "student" | "admin";

function areaOf(me: Me): Area {
  return me.permissions.includes("admin.access") ? "admin" : "student";
}

/**
 * Client-side guard for UX only (the API enforces every permission).
 * Redirects anonymous users to login and keeps each role in its own area.
 */
export function AuthGuard({ area, children }: { area: Area; children: (me: Me) => ReactNode }) {
  const { data: me, error, isPending } = useMe();
  const { locale } = useI18n();
  const router = useRouter();
  const pathname = usePathname();

  const wrongArea = me && areaOf(me) !== area;
  useEffect(() => {
    if (error) router.replace(`/${locale}/login?next=${encodeURIComponent(pathname)}`);
    else if (me && wrongArea) router.replace(`/${locale}/${areaOf(me)}`);
  }, [error, me, wrongArea, locale, pathname, router]);

  if (isPending || error || !me || wrongArea) {
    return (
      <div className="flex min-h-svh" aria-busy="true">
        <Skeleton className="hidden w-64 rounded-none md:block" />
        <div className="flex-1 space-y-4 p-6">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-32 w-full" />
        </div>
      </div>
    );
  }
  return <>{children(me)}</>;
}
