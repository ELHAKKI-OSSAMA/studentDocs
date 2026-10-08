"use client";

import { useState } from "react";
import { toast } from "sonner";
import { BadgeCheckIcon, SearchIcon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { Pager } from "@/components/pager";
import { EnrollmentBadge } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { localized } from "@/i18n/translate";
import { api } from "@/lib/api/client";
import { useApiQuery, useInvalidate } from "@/lib/api/hooks";
import type { EnrollmentReviewItem, EnrollmentStatus, Page } from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { formatDate, formatDateTime } from "@/lib/requests";

const LIMIT = 25;

function ReviewDialog({
  enrollment,
  decision,
  onClose,
}: {
  enrollment: EnrollmentReviewItem;
  decision: Exclude<EnrollmentStatus, "PENDING">;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const refresh = useInvalidate();
  const [note, setNote] = useState(enrollment.review_note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const rejecting = decision === "REJECTED";

  async function confirm() {
    if (rejecting && !note.trim()) {
      setError(t("errors.message_required"));
      return;
    }
    setBusy(true);
    try {
      await api(`/admin/enrollments/${enrollment.id}`, {
        method: "PATCH",
        body: { status: decision, review_note: note.trim() || null },
      });
      toast.success(t("enrollments.reviewed"));
      onClose();
      await refresh(["/admin/enrollments", "/admin/dashboard"]);
    } catch (err) {
      setError(errorMessage(t, err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t(rejecting ? "enrollments.reject" : "enrollments.verify")}</DialogTitle>
          <DialogDescription>
            {enrollment.student_name} · {enrollment.academic_year.label}
          </DialogDescription>
        </DialogHeader>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          {rejecting ? t("enrollments.rejectReason") : `${t("enrollments.note")} (${t("requests.optional")})`}
          <Textarea
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
              setError(null);
            }}
            maxLength={1000}
            rows={3}
            aria-invalid={!!error}
            data-testid="review-note-input"
          />
        </label>
        {error && (
          <Alert variant="destructive">
            <AlertDescription data-testid="review-error">{error}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant={rejecting ? "destructive" : "default"}
            onClick={confirm}
            disabled={busy}
            data-testid="confirm-review"
          >
            {t("requests.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function EnrollmentsReviewPage() {
  const { locale, t } = useI18n();
  const [status, setStatus] = useState<string>("PENDING");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [reviewing, setReviewing] = useState<{
    enrollment: EnrollmentReviewItem;
    decision: "VERIFIED" | "REJECTED";
  } | null>(null);
  const queue = useApiQuery<Page<EnrollmentReviewItem>>("/admin/enrollments", { status, q, limit: LIMIT, offset });

  return (
    <>
      <PageHeader title={t("enrollments.title")} />
      <Card>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_14rem]">
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
                placeholder={t("students.searchPlaceholder")}
                aria-label={t("common.search")}
                className="ps-8"
                maxLength={100}
                data-testid="enrollment-search"
              />
            </form>
            <NativeSelect
              aria-label={t("common.status")}
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
              data-testid="enrollment-status-filter"
            >
              <option value="">{t("requests.allStatuses")}</option>
              {(["PENDING", "VERIFIED", "REJECTED"] as const).map((s) => (
                <option key={s} value={s}>
                  {t(`enrollmentStatus.${s}`)}
                </option>
              ))}
            </NativeSelect>
          </div>

          <QueryState isPending={queue.isPending} error={queue.error} onRetry={() => queue.refetch()}>
            {queue.data?.items.length ? (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("requests.studentInfo")}</TableHead>
                      <TableHead>{t("requests.enrollment")}</TableHead>
                      <TableHead>{t("common.status")}</TableHead>
                      <TableHead>{t("enrollments.review")}</TableHead>
                      <TableHead>
                        <span className="sr-only">{t("common.actions")}</span>
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody data-testid="enrollments-review-table">
                    {queue.data.items.map((e) => (
                      <TableRow key={e.id} data-email={e.student_email}>
                        <TableCell>
                          <p className="font-medium">{e.student_name}</p>
                          <p className="text-xs text-muted-foreground" dir="ltr">
                            {e.student_email}
                            {e.student_number && ` · ${e.student_number}`}
                          </p>
                        </TableCell>
                        <TableCell className="text-sm">
                          <p>
                            {e.academic_year.label} · {localized(e.branch.category.name_i18n, locale)}
                          </p>
                          <p className="text-muted-foreground">
                            {localized(e.branch.name_i18n, locale)} · {localized(e.study_level.name_i18n, locale)}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {t("enrollments.declaredOn", { date: formatDate(e.created_at, locale) })}
                          </p>
                        </TableCell>
                        <TableCell>
                          <EnrollmentBadge status={e.status} />
                        </TableCell>
                        <TableCell className="max-w-56 text-xs text-muted-foreground" data-testid="review-info">
                          {e.reviewed_at ? (
                            <>
                              <p>
                                {t("enrollments.reviewedBy", {
                                  name: e.reviewer_name ?? "—",
                                  date: formatDateTime(e.reviewed_at, locale),
                                })}
                              </p>
                              {e.review_note && (
                                <p className="mt-1 text-foreground" dir="auto">
                                  {e.review_note}
                                </p>
                              )}
                            </>
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap justify-end gap-2">
                            {e.status !== "VERIFIED" && (
                              <Button
                                size="sm"
                                onClick={() => setReviewing({ enrollment: e, decision: "VERIFIED" })}
                                data-testid="verify-enrollment"
                              >
                                {t("enrollments.verify")}
                              </Button>
                            )}
                            {e.status !== "REJECTED" && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => setReviewing({ enrollment: e, decision: "REJECTED" })}
                                data-testid="reject-enrollment"
                              >
                                {t("enrollments.reject")}
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pager total={queue.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
              </>
            ) : (
              <EmptyState icon={BadgeCheckIcon} text={t("enrollments.empty")} />
            )}
          </QueryState>
        </CardContent>
      </Card>
      {reviewing && (
        <ReviewDialog
          enrollment={reviewing.enrollment}
          decision={reviewing.decision}
          onClose={() => setReviewing(null)}
        />
      )}
    </>
  );
}
