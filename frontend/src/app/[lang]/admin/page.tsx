"use client";

import Link from "next/link";
import {
  AtSignIcon,
  BadgeCheckIcon,
  CalendarPlusIcon,
  CalendarRangeIcon,
  CircleAlertIcon,
  FileStackIcon,
  GitBranchIcon,
  InboxIcon,
  MailWarningIcon,
  UserCheckIcon,
  UserCogIcon,
  UserXIcon,
  UsersIcon,
  type LucideIcon,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader, QueryState, StatCard } from "@/components/page";
import { StatusBadge } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { useApiQuery, useMe } from "@/lib/api/hooks";
import { REQUEST_STATUSES, type DashboardStats } from "@/lib/api/types";

type Tile = { label: string; value: number; icon: LucideIcon; id: string; href: string };

export default function AdminDashboard() {
  const { locale, t } = useI18n();
  const { data: me } = useMe();
  const stats = useApiQuery<DashboardStats>("/admin/dashboard");
  const s = stats.data;

  const requestTiles: Tile[] = s
    ? [
        { label: t("admin.requestsToday"), value: s.requests_today, icon: CalendarPlusIcon, id: "requests_today", href: "/admin/requests" },
        { label: t("admin.requestsOpen"), value: s.requests_open, icon: InboxIcon, id: "requests_open", href: "/admin/requests" },
        { label: t("admin.requestsUnassigned"), value: s.requests_unassigned, icon: UserXIcon, id: "requests_unassigned", href: "/admin/requests" },
        { label: t("admin.assignedToMe"), value: s.requests_assigned_to_me, icon: UserCheckIcon, id: "assigned_to_me", href: "/admin/requests" },
        { label: t("admin.requestsNeedInfo"), value: s.requests_needing_information, icon: CircleAlertIcon, id: "needs_info", href: "/admin/requests" },
        { label: t("admin.enrollmentsPending"), value: s.enrollments_pending, icon: BadgeCheckIcon, id: "enrollments_pending", href: "/admin/enrollments" },
      ]
    : [];
  const tiles: Tile[] = s
    ? [
        { label: t("admin.studentsTotal"), value: s.students_total, icon: UsersIcon, id: "students_total", href: "/admin/students" },
        { label: t("admin.pendingVerification"), value: s.students_pending_verification, icon: MailWarningIcon, id: "pending", href: "/admin/students" },
        { label: t("admin.staffTotal"), value: s.staff_total, icon: UserCogIcon, id: "staff", href: "/admin/users" },
        { label: t("admin.activeYears"), value: s.active_academic_years, icon: CalendarRangeIcon, id: "years", href: "/admin/academic-years" },
        { label: t("admin.activeBranches"), value: s.active_branches, icon: GitBranchIcon, id: "branches", href: "/admin/branches" },
        { label: t("admin.activeDocumentTypes"), value: s.active_document_types, icon: FileStackIcon, id: "doctypes", href: "/admin/document-types" },
        { label: t("admin.allowedDomains"), value: s.allowed_email_domains, icon: AtSignIcon, id: "domains", href: "/admin/settings" },
      ]
    : [];
  const byStatus = REQUEST_STATUSES.filter((st) => (s?.requests_by_status[st] ?? 0) > 0);

  const grid = (items: Tile[]) => (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((tile) => (
        <Link
          key={tile.id}
          href={`/${locale}${tile.href}`}
          className="rounded-xl focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <StatCard label={tile.label} value={tile.value} icon={tile.icon} testId={`stat-${tile.id}`} />
        </Link>
      ))}
    </div>
  );

  return (
    <>
      <PageHeader title={t("admin.dashboardTitle")} description={t("admin.welcome", { name: me?.first_name ?? "" })} />
      <QueryState isPending={stats.isPending} error={stats.error} onRetry={() => stats.refetch()}>
        <div className="flex flex-col gap-6">
          {grid(requestTiles)}
          <Card>
            <CardHeader>
              <CardTitle>{t("admin.byStatus")}</CardTitle>
            </CardHeader>
            <CardContent>
              {byStatus.length ? (
                <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" data-testid="requests-by-status">
                  {byStatus.map((st) => (
                    <li key={st} className="flex items-center justify-between gap-2 rounded-md border px-3 py-2">
                      <StatusBadge status={st} />
                      <span className="font-semibold tabular-nums">{s?.requests_by_status[st]}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState icon={InboxIcon} text={t("requests.empty")} />
              )}
            </CardContent>
          </Card>
          {grid(tiles)}
        </div>
      </QueryState>
    </>
  );
}
