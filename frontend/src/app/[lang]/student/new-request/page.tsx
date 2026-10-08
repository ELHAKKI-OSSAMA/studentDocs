"use client";

import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";
import { CircleCheckIcon, FileStackIcon, InfoIcon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { Field } from "@/components/auth-card";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { FilePicker, ScanNotice } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { localized } from "@/i18n/translate";
import { api } from "@/lib/api/client";
import { useApiQuery, useInvalidate } from "@/lib/api/hooks";
import type { DocumentType, Enrollment, RequestDetail } from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { buildRequestForm, validateDraft, type Selection } from "@/lib/requests";

function DocumentChoice({
  type,
  value,
  onChange,
}: {
  type: DocumentType;
  value: Selection[string] | undefined;
  onChange: (value: Selection[string] | undefined) => void;
}) {
  const { locale, t } = useI18n();
  const checked = !!value;
  const name = localized(type.name_i18n, locale);
  return (
    <li className="rounded-lg border p-4" data-testid="document-choice" data-code={type.code}>
      {/* Only the name labels the checkbox; the rules describe it. */}
      <label className="flex cursor-pointer items-start gap-3 font-medium">
        <Checkbox
          checked={checked}
          onCheckedChange={(on) => onChange(on ? { quantity: 1, file: null } : undefined)}
          aria-describedby={`rules-${type.id}`}
          className="mt-0.5"
        />
        {name}
      </label>
      <div id={`rules-${type.id}`} className="ps-7">
        {type.description_i18n && (
          <p className="text-sm text-muted-foreground">{localized(type.description_i18n, locale)}</p>
        )}
        <p className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground" data-testid="document-rules">
          <span>{t(`requests.delivery${type.delivery_mode}`)}</span>
          <span>{t("requests.processingDays", { n: type.processing_days })}</span>
          <span>{t("requests.maxQuantity", { n: type.max_quantity })}</span>
          {type.requires_attachment && (
            <span className="font-medium text-amber-700 dark:text-amber-400">{t("requests.attachmentRequired")}</span>
          )}
        </p>
      </div>
      {value && (
        <div className="mt-4 grid gap-4 ps-7 sm:grid-cols-[8rem_1fr]">
          <Field id={`qty-${type.id}`} label={t("requests.quantity")}>
            <Input
              id={`qty-${type.id}`}
              type="number"
              min={1}
              max={type.max_quantity}
              value={value.quantity}
              data-testid="document-quantity"
              onChange={(e) => onChange({ ...value, quantity: Number(e.target.value) })}
            />
          </Field>
          {type.requires_attachment && (
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium">{t("requests.attachmentRequired")}</span>
              <FilePicker
                multiple={false}
                files={value.file ? [value.file] : []}
                onChange={(files) => onChange({ ...value, file: files[0] ?? null })}
                testId="attachment-input"
              />
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function Confirmation({ request }: { request: RequestDetail }) {
  const { locale, t } = useI18n();
  return (
    <Card data-testid="request-created">
      <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
        <CircleCheckIcon className="size-10 text-emerald-600" aria-hidden />
        <p className="text-lg font-semibold">{t("requests.createdTitle")}</p>
        <p className="font-mono text-2xl font-semibold tracking-wide" dir="ltr" data-testid="request-reference">
          {request.reference}
        </p>
        <p className="text-sm text-muted-foreground">{t("requests.createdHint")}</p>
        {request.documents.length > 0 && (
          <p className="text-sm text-muted-foreground" data-testid="scan-pending-notice">
            {t("scan.receivedScanning")}
          </p>
        )}
        <div className="flex flex-wrap justify-center gap-2">
          <Link href={`/${locale}/student/requests/${request.id}`} className={buttonVariants()}>
            {t("requests.viewRequest")}
          </Link>
          <Link href={`/${locale}/student/requests`} className={buttonVariants({ variant: "outline" })}>
            {t("requests.myRequestsTitle")}
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

export default function NewRequestPage() {
  const { locale, t } = useI18n();
  const refresh = useInvalidate();
  const enrollments = useApiQuery<Enrollment[]>("/students/me/enrollments");
  // Only VERIFIED enrollments can back a request: PENDING / REJECTED are never selectable.
  const verified = useMemo(() => enrollments.data?.filter((e) => e.status === "VERIFIED") ?? [], [enrollments.data]);
  const pendingCount = enrollments.data?.filter((e) => e.status === "PENDING").length ?? 0;

  const [enrollmentId, setEnrollmentId] = useState("");
  const enrollment = verified.find((e) => e.id === enrollmentId);
  const types = useApiQuery<DocumentType[]>(
    "/catalog/document-types",
    { category_id: enrollment?.branch.category.id },
    { enabled: !!enrollment },
  );
  const [selection, setSelection] = useState<Selection>({});
  const [reason, setReason] = useState("");
  const [extraInfo, setExtraInfo] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<RequestDetail | null>(null);

  function selectEnrollment(id: string) {
    setEnrollmentId(id);
    setSelection({});
    setProblems([]);
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const draft = { enrollmentId, selection, reason, extraInfo };
    const found = validateDraft(draft, types.data ?? []);
    setProblems(found.map((k) => t(k)));
    if (found.length) return;
    setSubmitting(true);
    try {
      const request = await api<RequestDetail>("/requests", { method: "POST", body: buildRequestForm(draft) });
      setCreated(request);
      await refresh(["/requests", "/notifications"]);
    } catch (err) {
      setProblems([errorMessage(t, err)]);
    } finally {
      setSubmitting(false);
    }
  }

  if (created) {
    return (
      <>
        <PageHeader title={t("requests.newTitle")} />
        <Confirmation request={created} />
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("requests.newTitle")} description={t("requests.newSubtitle")} />
      <QueryState isPending={enrollments.isPending} error={enrollments.error} onRetry={() => enrollments.refetch()}>
        {!verified.length ? (
          <Alert data-testid="no-verified-enrollment">
            <InfoIcon />
            <AlertDescription className="flex flex-col items-start gap-3">
              {t("requests.noVerifiedEnrollment")}
              {pendingCount > 0 && <span>{t("requests.pendingEnrollments", { n: pendingCount })}</span>}
              <Link href={`/${locale}/student/profile`} className={buttonVariants({ size: "sm", variant: "outline" })}>
                {t("requests.goToProfile")}
              </Link>
            </AlertDescription>
          </Alert>
        ) : (
          <form onSubmit={onSubmit} noValidate className="flex flex-col gap-6" data-testid="new-request-form">
            <Card>
              <CardHeader>
                <CardTitle>{t("requests.enrollment")}</CardTitle>
                <CardDescription>
                  {t("requests.enrollmentHint")}
                  {pendingCount > 0 && <> {t("requests.pendingEnrollments", { n: pendingCount })}</>}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <NativeSelect
                  id="enrollment"
                  aria-label={t("requests.enrollment")}
                  value={enrollmentId}
                  onChange={(e) => selectEnrollment(e.target.value)}
                  data-testid="enrollment-select"
                >
                  <option value="" disabled>
                    {t("student.select")}
                  </option>
                  {verified.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.academic_year.label} · {localized(e.branch.name_i18n, locale)} ·{" "}
                      {localized(e.study_level.name_i18n, locale)}
                    </option>
                  ))}
                </NativeSelect>
                {enrollment && (
                  <dl className="grid gap-3 text-sm sm:grid-cols-4">
                    {[
                      ["requests.year", enrollment.academic_year.label],
                      ["requests.category", localized(enrollment.branch.category.name_i18n, locale)],
                      ["requests.branch", localized(enrollment.branch.name_i18n, locale)],
                      ["requests.level", localized(enrollment.study_level.name_i18n, locale)],
                    ].map(([label, value]) => (
                      <div key={label}>
                        <dt className="text-muted-foreground">{t(label as "requests.year")}</dt>
                        <dd className="font-medium">{value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </CardContent>
            </Card>

            {enrollment && (
              <Card>
                <CardHeader>
                  <CardTitle>{t("requests.documentsToRequest")}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <QueryState isPending={types.isPending} error={types.error} onRetry={() => types.refetch()}>
                    {types.data?.length ? (
                      <ul className="space-y-3">
                        {types.data.map((type) => (
                          <DocumentChoice
                            key={type.id}
                            type={type}
                            value={selection[type.id]}
                            onChange={(value) =>
                              setSelection((prev) => {
                                const next = { ...prev };
                                if (value) next[type.id] = value;
                                else delete next[type.id];
                                return next;
                              })
                            }
                          />
                        ))}
                      </ul>
                    ) : (
                      <EmptyState icon={FileStackIcon} text={t("requests.noDocumentTypes")} />
                    )}
                  </QueryState>
                  <ScanNotice />
                </CardContent>
              </Card>
            )}

            {enrollment && (
              <Card>
                <CardContent className="grid gap-4 pt-6">
                  <Field id="reason" label={`${t("requests.reason")} (${t("requests.optional")})`}>
                    <Textarea
                      id="reason"
                      value={reason}
                      maxLength={1000}
                      placeholder={t("requests.reasonPlaceholder")}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </Field>
                  <Field id="extra_info" label={`${t("requests.extraInfo")} (${t("requests.optional")})`}>
                    <Textarea
                      id="extra_info"
                      value={extraInfo}
                      maxLength={2000}
                      onChange={(e) => setExtraInfo(e.target.value)}
                    />
                  </Field>
                </CardContent>
              </Card>
            )}

            {problems.length > 0 && (
              <Alert variant="destructive" data-testid="form-errors">
                <AlertDescription>
                  <ul className="list-inside list-disc">
                    {problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}

            <div>
              <Button type="submit" disabled={submitting || !enrollment} data-testid="submit-request">
                {t("requests.submit")}
              </Button>
            </div>
          </form>
        )}
      </QueryState>
    </>
  );
}
