"use client";

import Link from "next/link";
import { useState } from "react";
import { BellIcon, CheckCheckIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { EmptyState, QueryState } from "@/components/page";
import { Pager } from "@/components/pager";
import { useI18n } from "@/i18n/client";
import type { TFunction } from "@/i18n/translate";
import { api } from "@/lib/api/client";
import { useApiQuery, useInvalidate } from "@/lib/api/hooks";
import type { AppNotification, Page } from "@/lib/api/types";
import { formatDateTime } from "@/lib/requests";
import { cn } from "cn";

export type Area = "student" | "admin";

/** In-app text of a notification (email delivery comes in a later phase). */
export function notificationText(n: AppNotification, t: TFunction): string {
  return t(`notifications.${n.type}`, {
    reference: n.reference ?? "",
    status: n.status ? t(`status.${n.status}`) : "",
  });
}

function requestHref(locale: string, area: Area, requestId: string) {
  return area === "student" ? `/${locale}/student/requests/${requestId}` : `/${locale}/admin/requests/${requestId}`;
}

export function NotificationList({ area, limit = 20, paged = true }: { area: Area; limit?: number; paged?: boolean }) {
  const { locale, t } = useI18n();
  const refresh = useInvalidate();
  const [offset, setOffset] = useState(0);
  const notes = useApiQuery<Page<AppNotification>>("/notifications", { limit, offset });

  const markRead = (id: string) =>
    api(`/notifications/${id}/read`, { method: "POST" })
      .then(() => refresh(["/notifications"]))
      .catch(() => undefined);

  return (
    <QueryState isPending={notes.isPending} error={notes.error} onRetry={() => notes.refetch()}>
      {notes.data?.items.length ? (
        <>
          <ul className="divide-y" data-testid="notification-list">
            {notes.data.items.map((n) => (
              <li key={n.id} className="flex items-start gap-3 py-3" data-type={n.type} data-unread={!n.read_at}>
                <span
                  className={cn("mt-1.5 size-2 shrink-0 rounded-full", n.read_at ? "bg-transparent" : "bg-primary")}
                  aria-hidden
                />
                <div className="min-w-0 flex-1 text-sm">
                  {n.request_id ? (
                    <Link
                      href={requestHref(locale, area, n.request_id)}
                      onClick={() => !n.read_at && markRead(n.id)}
                      className={cn("hover:underline", !n.read_at && "font-medium")}
                    >
                      {notificationText(n, t)}
                    </Link>
                  ) : (
                    <span>{notificationText(n, t)}</span>
                  )}
                  <p className="text-xs text-muted-foreground">{formatDateTime(n.created_at, locale)}</p>
                </div>
              </li>
            ))}
          </ul>
          {paged && <Pager total={notes.data.total} limit={limit} offset={offset} onChange={setOffset} />}
        </>
      ) : (
        <EmptyState icon={BellIcon} text={t("notifications.empty")} />
      )}
    </QueryState>
  );
}

export function MarkAllRead() {
  const { t } = useI18n();
  const refresh = useInvalidate();
  return (
    <Button
      variant="outline"
      onClick={() => api("/notifications/read-all", { method: "POST" }).then(() => refresh(["/notifications"]))}
      data-testid="mark-all-read"
    >
      <CheckCheckIcon />
      {t("notifications.markAllRead")}
    </Button>
  );
}

/** Header bell with the unread counter (polled; no websocket in this phase). */
export function NotificationBell({ area }: { area: Area }) {
  const { locale, t } = useI18n();
  const count = useApiQuery<{ unread: number }>("/notifications/unread-count", undefined, { refetchInterval: 30_000 });
  const unread = count.data?.unread ?? 0;
  return (
    <Link
      href={`/${locale}/${area}/notifications`}
      className={cn(buttonVariants({ variant: "ghost", size: "icon" }), "relative")}
      aria-label={`${t("notifications.title")}${unread ? ` (${unread})` : ""}`}
      data-testid="notification-bell"
    >
      <BellIcon />
      {unread > 0 && (
        <Badge className="absolute -end-1 -top-1 h-4 min-w-4 px-1 text-[10px]" data-testid="notification-count">
          {unread > 99 ? "99+" : unread}
        </Badge>
      )}
    </Link>
  );
}
