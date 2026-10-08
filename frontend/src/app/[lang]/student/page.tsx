"use client";

import Link from "next/link";
import {
  CircleAlertIcon,
  CircleCheckIcon,
  ClockIcon,
  InboxIcon,
  LoaderIcon,
  PlusIcon,
  UserIcon,
} from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, PageHeader, QueryState, StatCard } from "@/components/page";
import { NotificationList } from "@/components/notifications";
import { EnrollmentBadge, StatusBadge } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { localized } from "@/i18n/translate";
import { useApiQuery, useMe } from "@/lib/api/hooks";
import type { Enrollment, Page, RequestListItem, RequestSummary } from "@/lib/api/types";
import { formatDate } from "@/lib/requests";

export default function StudentDashboard() {
  const { locale, t } = useI18n();
  const { data: me } = useMe();
  const enrollments = useApiQuery<Enrollment[]>("/students/me/enrollments");
  const summary = useApiQuery<RequestSummary>("/requests/summary");
  const recent = useApiQuery<Page<RequestListItem>>("/requests", { limit: 5 });
  const count = (n: number | undefined) => (summary.data ? n : "…");

  return (
    <>
      <PageHeader
        title={t("student.greeting", { name: me?.first_name ?? "" })}
        actions={
          <Link href={`/${locale}/student/new-request`} className={buttonVariants()}>
            <PlusIcon />
            {t("student.newRequestCta")}
          </Link>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label={t("student.pending")} value={count(summary.data?.pending)} icon={ClockIcon} testId="stat-pending" />
        <StatCard
          label={t("student.inProgress")}
          value={count(summary.data?.in_progress)}
          icon={LoaderIcon}
          testId="stat-in-progress"
        />
        <StatCard
          label={t("student.actionRequired")}
          value={count(summary.data?.action_required)}
          icon={CircleAlertIcon}
          testId="stat-action-required"
        />
        <StatCard
          label={t("student.completed")}
          value={count(summary.data?.completed)}
          icon={CircleCheckIcon}
          testId="stat-completed"
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{t("student.recentRequests")}</CardTitle>
            <Link href={`/${locale}/student/requests`} className={buttonVariants({ variant: "ghost", size: "sm" })}>
              {t("requests.viewAll")}
            </Link>
          </CardHeader>
          <CardContent>
            <QueryState isPending={recent.isPending} error={recent.error} onRetry={() => recent.refetch()}>
              {recent.data?.items.length ? (
                <ul className="divide-y" data-testid="recent-requests">
                  {recent.data.items.map((r) => (
                    <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                      <div className="min-w-0">
                        <Link
                          href={`/${locale}/student/requests/${r.id}`}
                          className="font-mono text-sm font-medium text-primary hover:underline"
                          dir="ltr"
                        >
                          {r.reference}
                        </Link>
                        <p className="truncate text-xs text-muted-foreground">
                          {r.items.map((i) => localized(i.document_type.name_i18n, locale)).join(", ")} ·{" "}
                          {formatDate(r.created_at, locale)}
                        </p>
                      </div>
                      <StatusBadge status={r.status} />
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState icon={InboxIcon} text={t("requests.empty")} />
              )}
            </QueryState>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <UserIcon className="size-4" aria-hidden />
                {t("nav.profile")}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div>
                <p className="font-medium">
                  {me?.first_name} {me?.last_name}
                </p>
                <p className="text-muted-foreground" dir="ltr">
                  {me?.email}
                </p>
              </div>
              <QueryState isPending={enrollments.isPending} error={enrollments.error}>
                {enrollments.data?.length ? (
                  <ul className="space-y-1" data-testid="dashboard-enrollments">
                    {enrollments.data.map((e) => (
                      <li key={e.id} className="flex flex-wrap items-center gap-2 text-muted-foreground">
                        <span>
                          {e.academic_year.label} · {localized(e.branch.name_i18n, locale)} ·{" "}
                          {localized(e.study_level.name_i18n, locale)}
                        </span>
                        <EnrollmentBadge status={e.status} />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-muted-foreground">{t("student.noEnrollments")}</p>
                )}
              </QueryState>
              <Link
                href={`/${locale}/student/profile`}
                className={buttonVariants({ variant: "outline", size: "sm" })}
              >
                {t("common.edit")}
              </Link>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("student.notificationsTitle")}</CardTitle>
            </CardHeader>
            <CardContent>
              <NotificationList area="student" limit={5} paged={false} />
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
