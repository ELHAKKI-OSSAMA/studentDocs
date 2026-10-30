"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import {
  ArrowLeftIcon,
  DownloadIcon,
  PlusIcon,
  RefreshCwIcon,
  SparklesIcon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, QueryState } from "@/components/page";
import { AuthBadge, ConfidenceBadge, EmailStatusBadge, SandboxedHtml } from "@/components/emails";
import { DocumentList, hasPendingScan, ScanNotice, SCAN_POLL_MS, StatusBadge } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { localized, type TranslationKey } from "@/i18n/translate";
import { api, ApiError, downloadFile } from "@/lib/api/client";
import { useApiQuery, useInvalidate } from "@/lib/api/hooks";
import type {
  DocumentType,
  EmailCaseDetail,
  Page,
  PersonRef,
  RequestDetail,
  RequestDocument,
  RequestListItem,
  StudentDetail,
  StudentListItem,
} from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { formatBytes, formatDateTime, isUuid } from "@/lib/requests";

const LISTS = ["/admin/emails", "/admin/requests"];

function useAction() {
  const { t } = useI18n();
  const refresh = useInvalidate();
  const [busy, setBusy] = useState(false);
  async function run<T>(action: () => Promise<T>, success: (result: T) => string): Promise<T | undefined> {
    setBusy(true);
    try {
      const result = await action();
      toast.success(success(result));
      await refresh(LISTS);
      return result;
    } catch (err) {
      toast.error(errorMessage(t, err));
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { busy, run };
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-3 sm:gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="sm:col-span-2">{children}</dd>
    </div>
  );
}

// --- message -----------------------------------------------------------------------------------------

function MessageCard({ data }: { data: EmailCaseDetail }) {
  const { locale, t } = useI18n();
  const [view, setView] = useState<"text" | "html">("text");
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("emails.message")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <dl className="space-y-2">
          <Field label={t("emails.from")}>
            <span dir="auto">{data.from_name}</span>{" "}
            <span className="text-muted-foreground" dir="ltr" data-testid="email-from">
              &lt;{data.from_address}&gt;
            </span>
          </Field>
          <Field label={t("emails.to")}>
            <span dir="ltr">{[...data.to_addresses, ...data.cc_addresses].join(", ") || "—"}</span>
          </Field>
          <Field label={t("emails.receivedAt")}>{formatDateTime(data.received_at, locale)}</Field>
          {data.sent_at && <Field label={t("emails.sentAt")}>{formatDateTime(data.sent_at, locale)}</Field>}
          <Field label={t("emails.authentication")}>
            <AuthBadge verdict={data.authentication} />
          </Field>
        </dl>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant={view === "text" ? "default" : "outline"} onClick={() => setView("text")} data-testid="view-text">
            {t("emails.textView")}
          </Button>
          {data.body_html && (
            <Button size="sm" variant={view === "html" ? "default" : "outline"} onClick={() => setView("html")} data-testid="view-html">
              {t("emails.htmlView")}
            </Button>
          )}
          {data.can_read_raw && (
            <Button
              size="sm"
              variant="outline"
              className="ms-auto"
              data-testid="download-raw"
              onClick={() => downloadFile(`/admin/emails/${data.id}/raw`, `email-${data.id}.eml`).catch((err) => toast.error(errorMessage(t, err)))}
            >
              <DownloadIcon />
              {t("emails.downloadRaw")}
            </Button>
          )}
        </div>
        {view === "html" && data.body_html ? (
          <div className="space-y-1">
            <SandboxedHtml html={data.body_html} title={t("emails.htmlView")} />
            <p className="text-xs text-muted-foreground">{t("emails.htmlNote")}</p>
          </div>
        ) : (
          // Plain text rendered by React (escaped): never interpreted as HTML.
          <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-sm whitespace-pre-wrap" dir="auto" data-testid="email-body">
            {data.body_text || t("emails.noBody")}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}

function Warnings({ data }: { data: EmailCaseDetail }) {
  const { t } = useI18n();
  const flags = data.flags;
  const items: string[] = [];
  if (data.injection_suspected) items.push(t("emails.warnInjection"));
  if (data.infected_attachment) items.push(t("emails.warnInfected"));
  if (flags.ai_failed) items.push(t("emails.warnAiFailed"));
  if (flags.ai_disabled) items.push(t("emails.warnAiDisabled"));
  if (flags.reference_sender_mismatch) items.push(t("emails.warnReferenceMismatch"));
  if (typeof flags.unknown_reference === "string") items.push(t("emails.warnUnknownReference", { reference: flags.unknown_reference }));
  if (flags.body_truncated || flags.html_truncated) items.push(t("emails.warnTruncated"));
  if (flags.attachments_truncated) items.push(t("emails.warnAttachmentsTruncated"));
  if (!items.length) return null;
  return (
    <Card className="border-amber-300 dark:border-amber-800" data-testid="email-warnings">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <TriangleAlertIcon className="size-4 text-amber-600" aria-hidden />
          {t("emails.warnings")}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="list-disc space-y-1 ps-5 text-sm">
          {items.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function Attachments({ data }: { data: EmailCaseDetail }) {
  const { locale, t } = useI18n();
  const { busy, run } = useAction();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("emails.attachments")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <DocumentList
          basePath={`/admin/emails/${data.id}`}
          documents={data.documents}
          staff
          actions={(doc: RequestDocument) =>
            data.can_process && doc.scan_status === "ERROR" ? (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                data-testid="rescan-document"
                onClick={() => run(() => api(`/admin/emails/${data.id}/documents/${doc.id}/rescan`, { method: "POST" }), () => t("scan.rescanQueued"))}
              >
                <RefreshCwIcon />
                {t("scan.rescan")}
              </Button>
            ) : null
          }
        />
        {data.rejected_attachments.length > 0 && (
          <div className="space-y-1 text-sm" data-testid="rejected-attachments">
            <p className="font-medium">{t("emails.rejectedAttachments")}</p>
            <ul className="space-y-1">
              {data.rejected_attachments.map((r, i) => (
                <li key={`${r.filename}-${i}`} className="text-muted-foreground">
                  <span dir="auto">{r.filename}</span> · {formatBytes(r.size_bytes, locale)} ·{" "}
                  <span className="text-destructive">{t(`errors.${r.code}` as TranslationKey)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <ScanNotice />
      </CardContent>
    </Card>
  );
}

// --- identification ----------------------------------------------------------------------------------

function Identification({ data }: { data: EmailCaseDetail }) {
  const { t } = useI18n();
  const { busy, run } = useAction();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const results = useApiQuery<Page<StudentListItem>>("/admin/students", { q, limit: 5 }, { enabled: data.can_process && q.length > 1 });

  const associate = (studentId: string) =>
    run(() => api(`/admin/emails/${data.id}/student`, { method: "POST", body: { student_id: studentId } }), () => t("emails.associated"));

  return (
    <Card data-testid="identification">
      <CardHeader>
        <CardTitle>{t("emails.identification")}</CardTitle>
        {data.student ? (
          <CardDescription data-testid="identified-student" data-student-id={data.student.id}>
            {t("emails.identifiedAs")} · <span className="font-medium text-foreground">{data.student.first_name} {data.student.last_name}</span>{" "}
            · <span dir="ltr">{data.student.email}</span>
            {data.identification_method && <> · {t(`identificationMethod.${data.identification_method}`)}</>}
          </CardDescription>
        ) : (
          <CardDescription>{t("emails.notIdentified")}</CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="font-medium">{t("emails.candidates")}</p>
        {data.candidates.length ? (
          <ul className="space-y-2">
            {data.candidates.map((c) => (
              <li key={c.student.id} className="flex flex-wrap items-center gap-2 rounded-md border p-2" data-testid="candidate" data-student-id={c.student.id}>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">
                    {c.student.first_name} {c.student.last_name}
                  </p>
                  <p className="text-xs text-muted-foreground" dir="ltr">
                    {c.student.student_number ?? c.student.email}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {c.reasons.map((r) => t(`candidateReason.${r}` as TranslationKey)).join(" · ")} · {t("emails.score", { score: c.score })}
                  </p>
                </div>
                {data.can_process && data.student?.id !== c.student.id && (
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => associate(c.student.id)} data-testid="associate-candidate">
                    {t("emails.associate")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">{t("emails.noCandidate")}</p>
        )}
        {data.can_process && (
          <div className="space-y-2">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                setQ(search.trim());
              }}
            >
              <Input
                type="search"
                value={search}
                maxLength={100}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t("emails.searchStudent")}
                aria-label={t("emails.searchStudent")}
                data-testid="student-search"
              />
            </form>
            {results.data?.items.map((s) => (
              <div key={s.id} className="flex items-center gap-2" data-testid="student-result">
                <span className="flex-1">
                  {s.first_name} {s.last_name} · <span dir="ltr">{s.student_number ?? s.email}</span>
                </span>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => associate(s.id)} data-testid="associate-result">
                  {t("emails.associate")}
                </Button>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// --- AI proposal ------------------------------------------------------------------------------------

function ExtractionCard({ data }: { data: EmailCaseDetail }) {
  const { t } = useI18n();
  const { busy, run } = useAction();
  const ex = data.extraction;
  const out = ex?.output;
  return (
    <Card data-testid="extraction-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <SparklesIcon className="size-4" aria-hidden />
          {t("emails.extraction")}
        </CardTitle>
        <CardDescription>{t("emails.extractionHint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {ex && (
          <p className="text-xs text-muted-foreground" dir="ltr">
            {ex.model} · {ex.is_local_provider ? t("emails.providerLocal") : t("emails.providerExternal")} · {ex.prompt_version}
          </p>
        )}
        {out ? (
          <dl className="space-y-2">
            {out.student_number && <Field label={t("emails.studentNumber")}>{out.student_number.value}</Field>}
            {out.academic_year_label && <Field label={t("emails.academicYear")}>{out.academic_year_label.value}</Field>}
            {out.branch_hint && <Field label={t("emails.branchHint")}>{out.branch_hint.value}</Field>}
            {out.level_hint && <Field label={t("emails.levelHint")}>{out.level_hint.value}</Field>}
            <Field label={t("emails.requestedDocuments")}>
              {out.requested_documents.length ? (
                <ul className="space-y-1">
                  {out.requested_documents.map((d) => (
                    <li key={d.document_type_code} data-testid="extracted-document" data-code={d.document_type_code}>
                      <span className="font-mono text-xs" dir="ltr">
                        {d.document_type_code}
                      </span>
                      {d.quantity ? ` × ${d.quantity}` : ""}
                      <p className="text-xs text-muted-foreground" dir="auto">
                        « {d.quote} »
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                "—"
              )}
            </Field>
            {out.missing_information.length > 0 && (
              <Field label={t("emails.missingInformation")}>
                {out.missing_information.map((m) => t(`missingInfo.${m}` as TranslationKey)).join(", ")}
              </Field>
            )}
          </dl>
        ) : (
          <p className="text-muted-foreground" data-testid="no-extraction">
            {ex?.error_code ? errorMessage(t, new ApiError(0, ex.error_code, "")) : t("emails.noExtraction")}
          </p>
        )}
        {ex && ex.rule_violations.length > 0 && (
          <div data-testid="extraction-violations">
            <p className="font-medium">{t("emails.violations")}</p>
            <ul className="list-disc ps-5 text-xs text-muted-foreground">
              {ex.rule_violations.map((v, i) => (
                <li key={i}>
                  {v.field} · {t(`violation.${v.reason}` as TranslationKey)}
                  {v.code && (
                    <span dir="ltr" className="font-mono">
                      {" "}
                      ({v.code})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {data.can_reextract && (
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            data-testid="reextract"
            onClick={() => run(() => api(`/admin/emails/${data.id}/reextract`, { method: "POST" }), () => t("emails.reextractQueued"))}
          >
            <RefreshCwIcon />
            {t("emails.reextract")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

// --- correction + conversion -------------------------------------------------------------------------

type Item = { document_type_id: string; quantity: number; attachment_ids: string[] };

function initialItems(data: EmailCaseDetail, types: DocumentType[]): Item[] {
  if (data.correction?.requested_documents.length) {
    return data.correction.requested_documents.map((d) => ({ ...d, attachment_ids: [] }));
  }
  const byCode = new Map(types.map((ty) => [ty.code, ty.id]));
  const fromAi = (data.extraction?.output?.requested_documents ?? [])
    .filter((d) => byCode.has(d.document_type_code))
    .map((d) => ({ document_type_id: byCode.get(d.document_type_code)!, quantity: d.quantity ?? 1, attachment_ids: [] }));
  return fromAi.length ? fromAi : [{ document_type_id: "", quantity: 1, attachment_ids: [] }];
}

function RequestForm({ data, types }: { data: EmailCaseDetail; types: DocumentType[] }) {
  const { locale, t } = useI18n();
  const { busy, run } = useAction();
  const student = useApiQuery<StudentDetail>(`/admin/students/${data.student?.id}`, undefined, { enabled: !!data.student });
  const verified = useMemo(() => (student.data?.enrollments ?? []).filter((e) => e.status === "VERIFIED"), [student.data]);
  const matchedYear = data.extraction?.output?.matches?.academic_year_id;
  const [enrollmentId, setEnrollmentId] = useState(data.correction?.enrollment_id ?? "");
  const [items, setItems] = useState<Item[]>(() => initialItems(data, types));
  const [reason, setReason] = useState(data.correction?.reason ?? data.extraction?.output?.reason ?? "");
  const chosenEnrollment =
    enrollmentId || (verified.length === 1 ? verified[0].id : verified.find((e) => e.academic_year.id === matchedYear)?.id ?? "");
  const enrollment = verified.find((e) => e.id === chosenEnrollment);
  const allowed = types.filter(
    (ty) => !enrollment || !ty.allowed_categories.length || ty.allowed_categories.some((c) => c.id === enrollment.branch.category.id),
  );
  const clean = data.documents.filter((d) => d.scan_status === "CLEAN" && d.kind === "EMAIL_ATTACHMENT");
  const filled = items.filter((i) => i.document_type_id);

  function update(index: number, patch: Partial<Item>) {
    setItems((list) => list.map((it, i) => (i === index ? { ...it, ...patch } : it)));
  }

  const correction = () =>
    run(
      () =>
        api(`/admin/emails/${data.id}/extraction`, {
          method: "PUT",
          body: {
            enrollment_id: chosenEnrollment || null,
            requested_documents: filled.map(({ document_type_id, quantity }) => ({ document_type_id, quantity })),
            reason: reason || null,
          },
        }),
      () => t("emails.corrected"),
    );

  const convert = () =>
    run(
      () =>
        api<RequestDetail>(`/admin/emails/${data.id}/convert`, {
          method: "POST",
          body: {
            student_id: data.student!.id,
            enrollment_id: chosenEnrollment,
            items: filled,
            reason: reason || null,
            version: data.version,
          },
        }),
      (req) => t("emails.converted", { reference: req.reference }),
    );

  return (
    <Card data-testid="request-form">
      <CardHeader>
        <CardTitle>{t("emails.convertTitle")}</CardTitle>
        <CardDescription>{t("emails.convertHint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="space-y-1">
          <Label htmlFor="enrollment">{t("emails.enrollment")}</Label>
          {data.student ? (
            verified.length ? (
              <NativeSelect id="enrollment" value={chosenEnrollment} onChange={(e) => setEnrollmentId(e.target.value)} data-testid="enrollment-select">
                <option value="">{t("emails.chooseEnrollment")}</option>
                {verified.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.academic_year.label} · {localized(e.branch.name_i18n, locale)} · {localized(e.study_level.name_i18n, locale)}
                  </option>
                ))}
              </NativeSelect>
            ) : (
              <p className="text-muted-foreground">{student.isPending ? "…" : t("emails.noVerifiedEnrollment")}</p>
            )
          ) : (
            <p className="text-muted-foreground" data-testid="need-student">
              {t("emails.needStudent")}
            </p>
          )}
        </div>
        <div className="space-y-3">
          {items.map((item, index) => (
            <div key={index} className="space-y-2 rounded-md border p-3" data-testid="request-item">
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-48 flex-1 space-y-1">
                  <Label htmlFor={`type-${index}`}>{t("emails.documentType")}</Label>
                  <NativeSelect
                    id={`type-${index}`}
                    value={item.document_type_id}
                    onChange={(e) => update(index, { document_type_id: e.target.value })}
                    data-testid="item-type"
                  >
                    <option value="">{t("emails.chooseDocument")}</option>
                    {allowed.map((ty) => (
                      <option key={ty.id} value={ty.id}>
                        {localized(ty.name_i18n, locale)}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
                <div className="w-24 space-y-1">
                  <Label htmlFor={`qty-${index}`}>{t("emails.quantity")}</Label>
                  <Input
                    id={`qty-${index}`}
                    type="number"
                    min={1}
                    max={10}
                    value={item.quantity}
                    onChange={(e) => update(index, { quantity: Math.max(1, Math.min(10, Number(e.target.value) || 1)) })}
                    data-testid="item-quantity"
                  />
                </div>
                {items.length > 1 && (
                  <Button size="icon" variant="ghost" aria-label={t("emails.removeItem")} onClick={() => setItems((l) => l.filter((_, i) => i !== index))}>
                    <XIcon />
                  </Button>
                )}
              </div>
              {clean.length > 0 && (
                <fieldset className="space-y-1">
                  <legend className="text-xs text-muted-foreground">{t("emails.supportingFiles")}</legend>
                  {clean.map((doc) => (
                    <label key={doc.id} className="flex items-center gap-2 text-xs">
                      <input
                        type="checkbox"
                        checked={item.attachment_ids.includes(doc.id)}
                        onChange={(e) =>
                          update(index, {
                            attachment_ids: e.target.checked
                              ? [...item.attachment_ids, doc.id]
                              : item.attachment_ids.filter((id) => id !== doc.id),
                          })
                        }
                        data-testid="item-attachment"
                      />
                      <span dir="auto">{doc.filename}</span>
                    </label>
                  ))}
                </fieldset>
              )}
            </div>
          ))}
          <Button
            size="sm"
            variant="outline"
            onClick={() => setItems((l) => [...l, { document_type_id: "", quantity: 1, attachment_ids: [] }])}
            disabled={items.length >= 10}
            data-testid="add-item"
          >
            <PlusIcon />
            {t("emails.addItem")}
          </Button>
        </div>
        <div className="space-y-1">
          <Label htmlFor="reason">{t("emails.reason")}</Label>
          <Textarea id="reason" value={reason} maxLength={1000} onChange={(e) => setReason(e.target.value)} data-testid="request-reason" />
        </div>
        <p className="text-xs text-muted-foreground">{t("emails.correctionHint")}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy || !filled.length} onClick={correction} data-testid="save-correction">
            {t("emails.saveCorrection")}
          </Button>
          {data.can_convert && (
            <Button disabled={busy || !data.student || !chosenEnrollment || !filled.length} onClick={convert} data-testid="convert-submit">
              {t("emails.convert")}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// --- link --------------------------------------------------------------------------------------------

function LinkForm({ data }: { data: EmailCaseDetail }) {
  const { t } = useI18n();
  const { busy, run } = useAction();
  const [reference, setReference] = useState(data.reference_request?.reference ?? data.detected_reference ?? "");
  const [asResponse, setAsResponse] = useState(data.reference_request?.status === "NEEDS_INFORMATION");
  const [attachments, setAttachments] = useState<string[]>([]);
  const clean = data.documents.filter((d) => d.scan_status === "CLEAN" && d.kind === "EMAIL_ATTACHMENT");

  async function link() {
    await run(
      async () => {
        let requestId = data.reference_request?.reference === reference.trim() ? data.reference_request.id : "";
        if (!requestId) {
          const found = await api<Page<RequestListItem>>("/admin/requests", { query: { q: reference.trim(), limit: 5 } });
          requestId = found.items.find((r) => r.reference === reference.trim())?.id ?? "";
          if (!requestId) throw new ApiError(422, "invalid_reference", "");
        }
        return api<RequestDetail>(`/admin/emails/${data.id}/link`, {
          method: "POST",
          body: { request_id: requestId, attachment_ids: attachments, as_information_response: asResponse, version: data.version },
        });
      },
      (req) => t("emails.linked", { reference: req.reference }),
    );
  }

  return (
    <Card data-testid="link-form">
      <CardHeader>
        <CardTitle>{t("emails.link")}</CardTitle>
        <CardDescription>{t("emails.linkHint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {data.reference_request && (
          <p>
            {t("emails.detectedReference")} ·{" "}
            <span className="font-mono" dir="ltr">
              {data.reference_request.reference}
            </span>{" "}
            <StatusBadge status={data.reference_request.status} />
          </p>
        )}
        <div className="space-y-1">
          <Label htmlFor="link-ref">{t("emails.requestReference")}</Label>
          <Input
            id="link-ref"
            value={reference}
            dir="ltr"
            placeholder="REQ-2026-000001"
            maxLength={20}
            onChange={(e) => setReference(e.target.value)}
            data-testid="link-reference"
          />
        </div>
        {clean.map((doc) => (
          <label key={doc.id} className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={attachments.includes(doc.id)}
              onChange={(e) => setAttachments((l) => (e.target.checked ? [...l, doc.id] : l.filter((id) => id !== doc.id)))}
              data-testid="link-attachment"
            />
            <span dir="auto">{doc.filename}</span>
          </label>
        ))}
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={asResponse} onChange={(e) => setAsResponse(e.target.checked)} data-testid="link-as-response" />
          {t("emails.asResponse")}
        </label>
        <Button disabled={busy || !reference.trim()} onClick={link} data-testid="link-submit">
          {t("emails.linkSubmit")}
        </Button>
      </CardContent>
    </Card>
  );
}

// --- decisions -----------------------------------------------------------------------------------------

function Decisions({ data }: { data: EmailCaseDetail }) {
  const { locale, t } = useI18n();
  const { busy, run } = useAction();
  const [reason, setReason] = useState("");
  const assignees = useApiQuery<PersonRef[]>("/admin/requests/assignees", undefined, { enabled: data.can_process });
  const [assignee, setAssignee] = useState(data.assigned_to?.id ?? "");
  const post = (path: string, body: unknown, message: TranslationKey) =>
    run(() => api(`/admin/emails/${data.id}/${path}`, { method: "POST", body }), () => t(message));

  return (
    <Card data-testid="decisions">
      <CardHeader>
        <CardTitle>{t("emails.decision")}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {data.failure_code && (
          <p className="text-destructive" data-testid="failure-code">
            {t("emails.failure")} · {t(`emailFailure.${data.failure_code}` as TranslationKey)}
          </p>
        )}
        {data.dismiss_reason && (
          <p data-testid="dismiss-reason">
            {t("emails.reason")} · <span dir="auto">{data.dismiss_reason}</span>
          </p>
        )}
        {typeof data.flags.ignored_rule === "string" && (
          <p className="text-muted-foreground">{t(`ignoredRule.${data.flags.ignored_rule}` as TranslationKey)}</p>
        )}
        {data.can_dismiss && (
          <div className="space-y-2">
            <Label htmlFor="dismiss-reason">{t("emails.reasonLabel")}</Label>
            <Textarea id="dismiss-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} data-testid="dismiss-reason-input" />
            <div className="flex flex-wrap gap-2">
              <Button
                variant="destructive"
                disabled={busy || !reason.trim()}
                onClick={() => post("dismiss", { reason }, "emails.dismissed")}
                data-testid="dismiss-submit"
              >
                {t("emails.dismiss")}
              </Button>
              <Button variant="outline" disabled={busy || !reason.trim()} onClick={() => post("ignore", { reason }, "emails.ignored")} data-testid="ignore-submit">
                {t("emails.ignore")}
              </Button>
            </div>
          </div>
        )}
        {data.can_reopen && (
          <Button variant="outline" disabled={busy} onClick={() => post("reopen", { comment: null }, "emails.reopened")} data-testid="reopen">
            {t("emails.reopen")}
          </Button>
        )}
        {data.can_retry && (
          <Button variant="outline" disabled={busy} onClick={() => post("retry", undefined, "emails.retried")} data-testid="retry">
            {t("emails.retry")}
          </Button>
        )}
        {data.can_process && (
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-40 flex-1 space-y-1">
              <Label htmlFor="assignee">{t("emails.assignTo")}</Label>
              <NativeSelect id="assignee" value={assignee} onChange={(e) => setAssignee(e.target.value)} data-testid="email-assignee">
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
              disabled={busy || assignee === (data.assigned_to?.id ?? "")}
              onClick={() => post("assign", { assignee_id: assignee || null }, "emails.assigned")}
            >
              {t("common.save")}
            </Button>
          </div>
        )}
        {data.linked_request && (
          <Link href={`/${locale}/admin/requests/${data.linked_request.id}`} className={buttonVariants({ variant: "outline", size: "sm" })} data-testid="linked-request">
            {t("emails.openRequest")} · <span dir="ltr">{data.linked_request.reference}</span>
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

function History({ data }: { data: EmailCaseDetail }) {
  const { locale, t } = useI18n();
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("emails.history")}</CardTitle>
      </CardHeader>
      <CardContent>
        {data.reviews.length ? (
          <ol className="space-y-2 text-sm" data-testid="email-history">
            {data.reviews.map((r) => (
              <li key={r.id}>
                <p className="font-medium">{t(`reviewDecision.${r.decision}` as TranslationKey)}</p>
                <p className="text-xs text-muted-foreground">
                  {r.actor.first_name} {r.actor.last_name} · {formatDateTime(r.created_at, locale)}
                </p>
                {r.comment && (
                  <p className="text-xs" dir="auto">
                    {r.comment}
                  </p>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-muted-foreground">{t("emails.noHistory")}</p>
        )}
      </CardContent>
    </Card>
  );
}

export function EmailCaseView({ id }: { id: string }) {
  const { locale, t } = useI18n();
  const valid = isUuid(id);
  const query = useApiQuery<EmailCaseDetail>(`/admin/emails/${id}`, undefined, {
    enabled: valid,
    // Background steps (scans, extraction) update the case: poll while they run.
    refetchInterval: (d) =>
      d && (d.status === "NEW" || d.status === "AI_PROCESSING" || hasPendingScan(d.documents)) ? SCAN_POLL_MS : false,
  });
  const types = useApiQuery<DocumentType[]>("/catalog/document-types");
  const error = valid ? query.error : new ApiError(404, "not_found", "");
  const data = query.data;

  return (
    <>
      <div className="mb-2">
        <Link href={`/${locale}/admin/emails`} className={buttonVariants({ variant: "ghost", size: "sm" })}>
          <ArrowLeftIcon className="rtl:-scale-x-100" />
          {t("emails.back")}
        </Link>
      </div>
      <QueryState isPending={valid && query.isPending} error={error} onRetry={() => query.refetch()}>
        {data && (
          <>
            <PageHeader
              title={data.subject || t("emails.detailTitle")}
              description={
                <span className="flex flex-wrap items-center gap-2">
                  <EmailStatusBadge status={data.status} />
                  {data.review_confidence && <ConfidenceBadge level={data.review_confidence} />}
                </span>
              }
            />
            {(data.status === "NEW" || data.status === "AI_PROCESSING") && (
              <p className="mb-4 text-sm text-muted-foreground" data-testid="email-processing">
                {t("emails.processing")}
              </p>
            )}
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="flex min-w-0 flex-col gap-6 lg:col-span-2">
                <MessageCard data={data} />
                <Attachments data={data} />
                <ExtractionCard data={data} />
                {data.status === "NEEDS_REVIEW" && data.can_process && types.data && (
                  <RequestForm key={`${data.version}-${data.student?.id ?? ""}`} data={data} types={types.data} />
                )}
                {data.status === "NEEDS_REVIEW" && data.can_process && <LinkForm key={data.version} data={data} />}
              </div>
              <div className="flex min-w-0 flex-col gap-6">
                <Warnings data={data} />
                <Identification data={data} />
                <Decisions key={`${data.version}-${data.assigned_to?.id ?? ""}`} data={data} />
                <History data={data} />
              </div>
            </div>
          </>
        )}
      </QueryState>
    </>
  );
}
