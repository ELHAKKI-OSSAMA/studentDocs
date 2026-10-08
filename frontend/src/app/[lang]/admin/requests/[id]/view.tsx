"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { ArrowLeftIcon, UploadIcon } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { PageHeader, QueryState } from "@/components/page";
import { ADMIN_REQUEST_LISTS, RequestActions } from "@/components/request-actions";
import {
  DocumentList,
  EnrollmentBadge,
  FilePicker,
  MessageThread,
  RequestInfo,
  ScanNotice,
  StatusBadge,
  Timeline,
} from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { api, ApiError } from "@/lib/api/client";
import { useApiQuery, useInvalidate } from "@/lib/api/hooks";
import type { PersonRef, RequestDetail } from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { isUuid } from "@/lib/requests";

const LISTS = ADMIN_REQUEST_LISTS;

function Assignment({ request }: { request: RequestDetail }) {
  const { t } = useI18n();
  const refresh = useInvalidate();
  const assignees = useApiQuery<PersonRef[]>("/admin/requests/assignees", undefined, { enabled: request.can_assign });
  const [value, setValue] = useState(request.assigned_to?.id ?? "");
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await api(`/admin/requests/${request.id}/assign`, { method: "POST", body: { assignee_id: value || null } });
      toast.success(t("requests.assigned"));
      await refresh(LISTS);
    } catch (err) {
      toast.error(errorMessage(t, err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("requests.assignedTo")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p data-testid="assigned-to">
          {request.assigned_to
            ? `${request.assigned_to.first_name} ${request.assigned_to.last_name}`
            : t("requests.unassigned")}
        </p>
        {request.can_assign && (
          <div className="flex flex-wrap gap-2">
            <div className="min-w-48 flex-1">
              <NativeSelect
                aria-label={t("requests.assignTo")}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                data-testid="assignee-select"
              >
                <option value="">{t("requests.unassigned")}</option>
                {assignees.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.first_name} {p.last_name}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <Button
              variant="outline"
              onClick={save}
              disabled={busy || value === (request.assigned_to?.id ?? "")}
              data-testid="assign-save"
            >
              {t("common.save")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function UploadIssued({ request }: { request: RequestDetail }) {
  const { t } = useI18n();
  const refresh = useInvalidate();
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);

  async function upload() {
    if (!files.length) {
      toast.error(t("errors.file_required"));
      return;
    }
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    setBusy(true);
    try {
      await api(`/admin/requests/${request.id}/documents`, { method: "POST", body: form });
      setFiles([]);
      toast.success(t("requests.uploaded"));
      await refresh(LISTS);
    } catch (err) {
      toast.error(errorMessage(t, err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-dashed p-4" data-testid="issued-upload">
      <p className="text-sm font-medium">{t("requests.uploadIssued")}</p>
      <p className="text-xs text-muted-foreground">{t("requests.uploadIssuedHint")}</p>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <FilePicker files={files} onChange={setFiles} testId="issued-input" />
        <Button onClick={upload} disabled={busy || !files.length} data-testid="issued-submit">
          <UploadIcon />
          {t("requests.upload")}
        </Button>
      </div>
    </div>
  );
}

export function RequestView({ id }: { id: string }) {
  const { locale, t } = useI18n();
  const valid = isUuid(id);
  const request = useApiQuery<RequestDetail>(`/admin/requests/${id}`, undefined, { enabled: valid });
  const error = valid ? request.error : new ApiError(404, "not_found", "");
  const data = request.data;
  const basePath = `/admin/requests/${id}`;

  return (
    <>
      <div className="mb-2">
        <Link href={`/${locale}/admin/requests`} className={buttonVariants({ variant: "ghost", size: "sm" })}>
          <ArrowLeftIcon className="rtl:-scale-x-100" />
          {t("nav.requests")}
        </Link>
      </div>
      <QueryState isPending={valid && request.isPending} error={error} onRetry={() => request.refetch()}>
        {data && (
          <>
            <PageHeader
              title={t("requests.detailTitle", { reference: data.reference })}
              description={<StatusBadge status={data.status} />}
            />
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="flex flex-col gap-6 lg:col-span-2">
                <Card>
                  <CardHeader>
                    <CardTitle>{t("requests.studentInfo")}</CardTitle>
                    {data.student && (
                      <CardDescription>
                        <span className="font-medium text-foreground" data-testid="student-name">
                          {data.student.first_name} {data.student.last_name}
                        </span>{" "}
                        · <span dir="ltr">{data.student.email}</span>
                        {data.student.student_number && (
                          <>
                            {" "}
                            · <span dir="ltr">{data.student.student_number}</span>
                          </>
                        )}
                      </CardDescription>
                    )}
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-muted-foreground">{t("requests.enrollmentStatus")}</span>
                      <EnrollmentBadge status={data.enrollment_status} />
                    </div>
                    <RequestInfo request={data} />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>{t("requests.documents")}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <DocumentList basePath={basePath} documents={data.documents.filter((d) => d.kind !== "MESSAGE")} />
                    {data.can_upload_document && <UploadIssued request={data} />}
                    <ScanNotice />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>{t("requests.messages")}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <MessageThread basePath={basePath} side="STAFF" canPost={data.can_message} invalidate={LISTS} />
                  </CardContent>
                </Card>
              </div>
              <div className="flex flex-col gap-6">
                <RequestActions request={data} />
                <Assignment key={data.assigned_to?.id ?? "none"} request={data} />
                <Card>
                  <CardHeader>
                    <CardTitle>{t("requests.timeline")}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <Timeline history={data.history} />
                  </CardContent>
                </Card>
              </div>
            </div>
          </>
        )}
      </QueryState>
    </>
  );
}
