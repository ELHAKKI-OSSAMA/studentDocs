"use client";

import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { ArchiveIcon, ArrowLeftIcon, FileStackIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Field } from "@/components/auth-card";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { Pager } from "@/components/pager";
import { DocumentList, EnrollmentBadge, StatusBadge } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { localized } from "@/i18n/translate";
import { api } from "@/lib/api/client";
import { useApiQuery, useHasPermission, useInvalidate } from "@/lib/api/hooks";
import type {
  DocumentType,
  IssuedDocument,
  Page,
  RequestListItem,
  StudentDeposit,
  StudentDetail,
} from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/requests";

const LIMIT = 10;

function Profile({ student }: { student: StudentDetail }) {
  const { locale, t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("students.profile")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <dl className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3">
          <div>
            <dt className="text-muted-foreground">{t("auth.email")}</dt>
            <dd className="font-medium break-all" dir="ltr">{student.email}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("student.studentNumber")}</dt>
            <dd className="font-medium" dir="ltr">{student.student_number ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{t("students.registeredAt")}</dt>
            <dd className="font-medium">{formatDateTime(student.created_at, locale)}</dd>
          </div>
        </dl>
        <div>
          <p className="mb-2 font-medium">{t("students.enrollments")}</p>
          {student.enrollments.length ? (
            <ul className="divide-y rounded-lg border" data-testid="student-enrollments">
              {student.enrollments.map((e) => (
                <li key={e.id} className="flex flex-wrap items-center gap-2 p-3">
                  <span className="flex-1">
                    {e.academic_year.label} · {localized(e.branch.name_i18n, locale)} ·{" "}
                    {localized(e.study_level.name_i18n, locale)}
                  </span>
                  <EnrollmentBadge status={e.status} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground">{t("common.noData")}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Requests({ studentId }: { studentId: string }) {
  const { locale, t } = useI18n();
  const [offset, setOffset] = useState(0);
  const list = useApiQuery<Page<RequestListItem>>("/admin/requests", { student_id: studentId, limit: LIMIT, offset });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("students.studentRequests")}</CardTitle>
      </CardHeader>
      <CardContent>
        <QueryState isPending={list.isPending} error={list.error} onRetry={() => list.refetch()}>
          {list.data?.items.length ? (
            <>
              <Table data-testid="student-requests">
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("students.request")}</TableHead>
                    <TableHead>{t("requests.documentsToRequest")}</TableHead>
                    <TableHead>{t("common.status")}</TableHead>
                    <TableHead>{t("requests.year")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {list.data.items.map((r) => (
                    <TableRow key={r.id}>
                      <TableCell>
                        <Link
                          href={`/${locale}/admin/requests/${r.id}`}
                          className="font-mono font-medium hover:underline"
                          dir="ltr"
                        >
                          {r.reference}
                        </Link>
                        <p className="text-xs text-muted-foreground">{formatDateTime(r.created_at, locale)}</p>
                      </TableCell>
                      <TableCell className="max-w-56 truncate">
                        {r.items.map((i) => localized(i.document_type.name_i18n, locale)).join(", ")}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={r.status} />
                      </TableCell>
                      <TableCell>{r.academic_year.label}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <Pager total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
            </>
          ) : (
            <EmptyState icon={FileStackIcon} text={t("students.noRequests")} />
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function Documents({ studentId }: { studentId: string }) {
  const { locale, t } = useI18n();
  const docs = useApiQuery<IssuedDocument[]>(`/admin/students/${studentId}/documents`);
  // One list per request: downloads go through that request's authorized endpoint.
  const groups = useMemo(() => {
    const byRequest = new Map<string, { reference: string; documents: IssuedDocument[] }>();
    for (const doc of docs.data ?? []) {
      const group = byRequest.get(doc.request_id) ?? { reference: doc.reference, documents: [] };
      group.documents.push(doc);
      byRequest.set(doc.request_id, group);
    }
    return [...byRequest.entries()];
  }, [docs.data]);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("students.studentDocuments")}</CardTitle>
      </CardHeader>
      <CardContent>
        <QueryState isPending={docs.isPending} error={docs.error} onRetry={() => docs.refetch()}>
          {groups.length ? (
            <div className="space-y-4" data-testid="student-documents">
              {groups.map(([requestId, group]) => (
                <div key={requestId} className="space-y-2">
                  <Link
                    href={`/${locale}/admin/requests/${requestId}`}
                    className="font-mono text-sm font-medium hover:underline"
                    dir="ltr"
                  >
                    {group.reference}
                  </Link>
                  <DocumentList basePath={`/admin/requests/${requestId}`} documents={group.documents} staff />
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("requests.noDocuments")}</p>
          )}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function Deposits({ studentId }: { studentId: string }) {
  const { locale, t } = useI18n();
  const refresh = useInvalidate();
  const canManage = useHasPermission("students.manage");
  const path = `/admin/students/${studentId}/deposits`;
  const deposits = useApiQuery<StudentDeposit[]>(path);
  const types = useApiQuery<DocumentType[]>("/admin/catalog/document-types", undefined, { enabled: canManage });
  const depositTypes = (types.data ?? []).filter((d) => d.requires_deposit);
  const [typeId, setTypeId] = useState("");
  const [depositedOn, setDepositedOn] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const date = new Intl.DateTimeFormat(locale, { dateStyle: "medium" });

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true);
    try {
      await action();
      toast.success(success);
      await refresh([path]);
      return true;
    } catch (err) {
      toast.error(errorMessage(t, err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    const body = { document_type_id: typeId, deposited_on: depositedOn, note: note.trim() || null };
    if (await run(() => api(path, { method: "POST", body }), t("deposits.recorded"))) {
      setTypeId("");
      setDepositedOn("");
      setNote("");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("deposits.title")}</CardTitle>
        <CardDescription>{t("deposits.hint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <QueryState isPending={deposits.isPending} error={deposits.error} onRetry={() => deposits.refetch()}>
          {deposits.data?.length ? (
            <ul className="divide-y rounded-lg border" data-testid="deposit-list">
              {deposits.data.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center gap-3 p-3 text-sm" data-testid="deposit-row">
                  <ArchiveIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{localized(d.document_type.name_i18n, locale)}</p>
                    <p className="text-xs text-muted-foreground">
                      {t("deposits.depositedOn", { date: date.format(new Date(d.deposited_on)) })}
                      {d.note && <> · {d.note}</>}
                    </p>
                  </div>
                  {d.returned_at ? (
                    <Badge variant="outline">
                      {t("deposits.returnedOn", { date: date.format(new Date(d.returned_at)) })}
                    </Badge>
                  ) : (
                    <>
                      <Badge variant="secondary">{t("deposits.held")}</Badge>
                      {canManage && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          data-testid="deposit-return"
                          onClick={() =>
                            run(() => api(`${path}/${d.id}/return`, { method: "POST" }), t("deposits.returned"))
                          }
                        >
                          {t("deposits.return")}
                        </Button>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">{t("deposits.none")}</p>
          )}
        </QueryState>
        {canManage &&
          (depositTypes.length ? (
            <form onSubmit={add} className="grid gap-3 sm:grid-cols-2 sm:items-end" data-testid="deposit-form">
              <Field id="deposit-type" label={t("deposits.documentType")}>
                <NativeSelect
                  id="deposit-type"
                  value={typeId}
                  required
                  onChange={(e) => setTypeId(e.target.value)}
                >
                  <option value="" disabled>
                    {t("student.select")}
                  </option>
                  {depositTypes.map((d) => (
                    <option key={d.id} value={d.id}>
                      {localized(d.name_i18n, locale)}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field id="deposit-date" label={t("deposits.date")}>
                <Input
                  id="deposit-date"
                  type="date"
                  required
                  value={depositedOn}
                  max={new Date().toISOString().slice(0, 10)}
                  onChange={(e) => setDepositedOn(e.target.value)}
                />
              </Field>
              <Field id="deposit-note" label={`${t("deposits.note")} (${t("requests.optional")})`}>
                <Input id="deposit-note" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <Button type="submit" disabled={busy || !typeId || !depositedOn}>
                {t("deposits.add")}
              </Button>
            </form>
          ) : (
            types.data && <p className="text-sm text-muted-foreground">{t("deposits.noTypes")}</p>
          ))}
      </CardContent>
    </Card>
  );
}

export function StudentView({ id }: { id: string }) {
  const { locale, t } = useI18n();
  const student = useApiQuery<StudentDetail>(`/admin/students/${id}`);
  const canReadRequests = useHasPermission("requests.read");
  const data = student.data;
  return (
    <>
      <Link href={`/${locale}/admin/students`} className={buttonVariants({ variant: "ghost", size: "sm" })}>
        <ArrowLeftIcon className="rtl:rotate-180" aria-hidden />
        {t("students.backToList")}
      </Link>
      <QueryState isPending={student.isPending} error={student.error} onRetry={() => student.refetch()}>
        {data && (
          <div className="flex flex-col gap-6" data-testid="student-detail">
            <PageHeader title={`${data.first_name} ${data.last_name}`} />
            <div className="grid gap-6 xl:grid-cols-2">
              <Profile student={data} />
              <Deposits studentId={data.id} />
            </div>
            {canReadRequests && <Requests studentId={data.id} />}
            {canReadRequests && <Documents studentId={data.id} />}
          </div>
        )}
      </QueryState>
    </>
  );
}
