"use client";

import Link from "next/link";
import { useState } from "react";
import { MailIcon, PaperclipIcon, SearchIcon, ShieldAlertIcon, ShieldXIcon, TriangleAlertIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, PageHeader, QueryState, StatCard } from "@/components/page";
import { Pager } from "@/components/pager";
import { ConfidenceBadge, EmailStatusBadge } from "@/components/emails";
import { useI18n } from "@/i18n/client";
import { useApiQuery } from "@/lib/api/hooks";
import {
  EMAIL_CASE_STATUSES,
  REVIEW_CONFIDENCES,
  type EmailCaseListItem,
  type Page,
} from "@/lib/api/types";
import { formatDateTime } from "@/lib/requests";

const LIMIT = 25;

type EmailStats = {
  awaiting_review: number;
  mailbox_last_success_at: string | null;
  mailbox_last_error: string | null;
};

export default function AdminEmailsPage() {
  const { locale, t } = useI18n();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({ status: "", confidence: "", assigned: "" });
  const [offset, setOffset] = useState(0);
  const cases = useApiQuery<Page<EmailCaseListItem>>(
    "/admin/emails",
    { ...filters, q, limit: LIMIT, offset },
    // New emails arrive in the background (mailbox polling): refresh the queue regularly.
    { refetchInterval: 15_000 },
  );
  const stats = useApiQuery<EmailStats>("/admin/emails/stats", undefined, { refetchInterval: 30_000 });

  function setFilter(name: keyof typeof filters, value: string) {
    setFilters((f) => ({ ...f, [name]: value }));
    setOffset(0);
  }

  return (
    <>
      <PageHeader title={t("emails.title")} description={t("emails.description")} />
      {stats.data && (
        <div className="mb-6 grid gap-4 sm:grid-cols-2">
          <StatCard label={t("emails.awaitingReview")} value={stats.data.awaiting_review} icon={MailIcon} />
          <Card>
            <CardContent className="space-y-1 text-sm">
              <p className="text-muted-foreground">{t("emails.lastPoll")}</p>
              <p data-testid="mailbox-last-success">
                {stats.data.mailbox_last_success_at ? formatDateTime(stats.data.mailbox_last_success_at, locale) : "—"}
              </p>
              {stats.data.mailbox_last_error && (
                <p className="text-destructive" data-testid="mailbox-error">
                  {t("emails.mailboxError", { code: stats.data.mailbox_last_error })}
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      )}
      <Card>
        <CardContent className="space-y-4">
          <form
            className="relative"
            onSubmit={(e) => {
              e.preventDefault();
              setQ(search.trim());
              setOffset(0);
            }}
          >
            <SearchIcon className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("emails.searchPlaceholder")}
              aria-label={t("common.search")}
              className="ps-8"
              maxLength={100}
              data-testid="email-search"
            />
          </form>
          <div className="grid gap-3 sm:grid-cols-3">
            <NativeSelect
              aria-label={t("common.status")}
              value={filters.status}
              onChange={(e) => setFilter("status", e.target.value)}
              data-testid="email-filter-status"
            >
              <option value="">{t("emails.allStatuses")}</option>
              {EMAIL_CASE_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`emailStatus.${s}`)}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label={t("reviewConfidence.hint")}
              value={filters.confidence}
              onChange={(e) => setFilter("confidence", e.target.value)}
              data-testid="email-filter-confidence"
            >
              <option value="">{t("emails.allConfidence")}</option>
              {REVIEW_CONFIDENCES.map((c) => (
                <option key={c} value={c}>
                  {t(`reviewConfidence.${c}`)}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label={t("requests.assignedTo")}
              value={filters.assigned}
              onChange={(e) => setFilter("assigned", e.target.value)}
            >
              <option value="">{t("requests.assignedAll")}</option>
              <option value="me">{t("requests.assignedMe")}</option>
              <option value="unassigned">{t("requests.assignedNone")}</option>
            </NativeSelect>
          </div>

          <QueryState isPending={cases.isPending} error={cases.error} onRetry={() => cases.refetch()}>
            {cases.data?.items.length ? (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("emails.from")}</TableHead>
                      <TableHead>{t("emails.subject")}</TableHead>
                      <TableHead>{t("emails.student")}</TableHead>
                      <TableHead>{t("common.status")}</TableHead>
                      <TableHead>{t("emails.receivedAt")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody data-testid="email-cases-table">
                    {cases.data.items.map((c) => (
                      <TableRow key={c.id} data-testid="email-case-row" data-status={c.status} data-from={c.from_address}>
                        <TableCell>
                          <p className="font-medium" dir="auto">
                            {c.from_name ?? c.from_address}
                          </p>
                          <p className="text-xs text-muted-foreground" dir="ltr">
                            {c.from_address}
                          </p>
                        </TableCell>
                        <TableCell className="max-w-72">
                          <Link
                            href={`/${locale}/admin/emails/${c.id}`}
                            className="line-clamp-2 font-medium text-primary hover:underline"
                            dir="auto"
                            data-testid="email-case-link"
                          >
                            {c.subject || "—"}
                          </Link>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            {c.detected_reference && (
                              <span className="font-mono" dir="ltr">
                                {c.detected_reference}
                              </span>
                            )}
                            {c.attachment_count > 0 && (
                              <span className="inline-flex items-center gap-1">
                                <PaperclipIcon className="size-3" aria-hidden />
                                {t("emails.attachmentsCount", { n: c.attachment_count })}
                              </span>
                            )}
                            {c.injection_suspected && (
                              <ShieldAlertIcon className="size-3.5 text-amber-600" aria-label={t("emails.warnInjection")} />
                            )}
                            {c.infected_attachment && (
                              <ShieldXIcon className="size-3.5 text-destructive" aria-label={t("emails.warnInfected")} />
                            )}
                            {c.ai_failed && (
                              <TriangleAlertIcon className="size-3.5 text-amber-600" aria-label={t("emails.warnAiFailed")} />
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-sm">
                          {c.student ? (
                            <>
                              <p>
                                {c.student.first_name} {c.student.last_name}
                              </p>
                              <p className="text-xs text-muted-foreground" dir="ltr">
                                {c.student.student_number ?? c.student.email}
                              </p>
                            </>
                          ) : (
                            <span className="text-muted-foreground">
                              {t("emails.candidatesCount", { n: c.candidate_count })}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="space-y-1">
                          <EmailStatusBadge status={c.status} />
                          {c.review_confidence && (
                            <div>
                              <ConfidenceBadge level={c.review_confidence} />
                            </div>
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{formatDateTime(c.received_at, locale)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pager total={cases.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
              </>
            ) : (
              <EmptyState icon={MailIcon} text={t("emails.empty")} />
            )}
          </QueryState>
        </CardContent>
      </Card>
    </>
  );
}
