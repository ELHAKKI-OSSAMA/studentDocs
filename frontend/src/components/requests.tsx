"use client";

/** Building blocks shared by the student and admin request screens. */

import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import {
  CircleDotIcon,
  DownloadIcon,
  FileIcon,
  MessageSquareIcon,
  PaperclipIcon,
  SendIcon,
  ShieldAlertIcon,
  XIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { EmptyState, QueryState } from "@/components/page";
import { useI18n } from "@/i18n/client";
import { localized, type TranslationKey } from "@/i18n/translate";
import { api, downloadFile } from "@/lib/api/client";
import { useApiQuery, useInvalidate } from "@/lib/api/hooks";
import type {
  EnrollmentStatus,
  HistoryEntry,
  RequestDocument,
  RequestDetail,
  RequestMessage,
  RequestStatus,
} from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import {
  buildMessageForm,
  FILE_ACCEPT,
  fileProblem,
  formatBytes,
  formatDateTime,
  statusTone,
  type StatusTone,
} from "@/lib/requests";
import { cn } from "cn";

const TONE_CLASSES: Record<StatusTone, string> = {
  neutral: "bg-muted text-foreground",
  info: "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200",
  warning: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  success: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  danger: "bg-destructive/10 text-destructive",
};

export function StatusBadge({ status }: { status: RequestStatus }) {
  const { t } = useI18n();
  return (
    <Badge className={TONE_CLASSES[statusTone(status)]} data-testid="request-status" data-status={status}>
      {t(`status.${status}`)}
    </Badge>
  );
}

export function EnrollmentBadge({ status }: { status: EnrollmentStatus }) {
  const { t } = useI18n();
  const tone: StatusTone = status === "VERIFIED" ? "success" : status === "REJECTED" ? "danger" : "warning";
  return (
    <Badge className={TONE_CLASSES[tone]} data-testid="enrollment-status" data-status={status}>
      {t(`enrollmentStatus.${status}`)}
    </Badge>
  );
}

function actorLabel(role: string): TranslationKey {
  if (role === "STUDENT") return "requests.studentRole";
  if (role === "SYSTEM") return "requests.system";
  return "requests.administration";
}

export function Timeline({ history }: { history: HistoryEntry[] }) {
  const { locale, t } = useI18n();
  return (
    <ol className="relative space-y-5 border-s ps-6" data-testid="timeline">
      {history.map((h, i) => (
        <li key={`${h.to_status}-${h.created_at}-${i}`} className="relative">
          <CircleDotIcon
            className={cn(
              "absolute -start-[1.95rem] top-0.5 size-4 bg-background",
              i === history.length - 1 ? "text-primary" : "text-muted-foreground",
            )}
            aria-hidden
          />
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={h.to_status} />
            <span className="text-xs text-muted-foreground">
              {formatDateTime(h.created_at, locale)} · {t(actorLabel(h.actor_role))}
            </span>
          </div>
          {h.comment && (
            <p className="mt-1 text-sm whitespace-pre-line" dir="auto">
              {h.comment}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}

function DownloadButton({ basePath, doc }: { basePath: string; doc: RequestDocument }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={busy}
      data-testid="download-document"
      onClick={async () => {
        setBusy(true);
        try {
          await downloadFile(`${basePath}/documents/${doc.id}/download`, doc.filename);
        } catch (err) {
          toast.error(errorMessage(t, err));
        } finally {
          setBusy(false);
        }
      }}
    >
      <DownloadIcon />
      {t("requests.download")}
    </Button>
  );
}

/** File list with downloads through the authorized API endpoint (`basePath` = request API path). */
export function DocumentList({ basePath, documents }: { basePath: string; documents: RequestDocument[] }) {
  const { locale, t } = useI18n();
  if (!documents.length) return <p className="text-sm text-muted-foreground">{t("requests.noDocuments")}</p>;
  return (
    <ul className="divide-y rounded-lg border" data-testid="document-list">
      {documents.map((doc) => (
        <li key={doc.id} className="flex flex-wrap items-center gap-3 p-3" data-kind={doc.kind}>
          <FileIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium" dir="auto">
              {doc.filename}
            </p>
            <p className="text-xs text-muted-foreground">
              {t(`requests.kind${doc.kind}`)} · {formatBytes(doc.size_bytes, locale)} ·{" "}
              {formatDateTime(doc.created_at, locale)}
            </p>
          </div>
          <DownloadButton basePath={basePath} doc={doc} />
        </li>
      ))}
    </ul>
  );
}

export function ScanNotice() {
  const { t } = useI18n();
  return (
    <p className="flex items-start gap-2 text-xs text-muted-foreground">
      <ShieldAlertIcon className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      {t("requests.notScanned")}
    </p>
  );
}

/** Multi-file picker with the same checks as the backend (type, size). */
export function FilePicker({
  files,
  onChange,
  multiple = true,
  testId,
  id,
}: {
  files: File[];
  onChange: (files: File[]) => void;
  multiple?: boolean;
  testId?: string;
  id?: string;
}) {
  const { t } = useI18n();
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="space-y-2">
      <input
        ref={input}
        id={id}
        type="file"
        accept={FILE_ACCEPT}
        multiple={multiple}
        className="sr-only"
        data-testid={testId}
        onChange={(e) => {
          const picked = Array.from(e.target.files ?? []);
          e.target.value = "";
          const rejected = picked.map(fileProblem).find(Boolean);
          if (rejected) toast.error(t(rejected));
          const ok = picked.filter((f) => !fileProblem(f));
          onChange(multiple ? [...files, ...ok] : ok.slice(0, 1));
        }}
      />
      <Button type="button" variant="outline" size="sm" onClick={() => input.current?.click()}>
        <PaperclipIcon />
        {t("requests.attachFiles")}
      </Button>
      {files.length > 0 && (
        <ul className="space-y-1">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-2 text-sm">
              <FileIcon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate" dir="auto">
                {f.name}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label={t("common.delete")}
                onClick={() => onChange(files.filter((_, j) => j !== i))}
              >
                <XIcon />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">{t("requests.attachmentHint")}</p>
    </div>
  );
}

function messageTitle(m: RequestMessage, side: "STUDENT" | "STAFF", t: (k: TranslationKey) => string) {
  if (m.author_side === side) return t("requests.you");
  return m.author_side === "STAFF" && side === "STUDENT" ? t("requests.administration") : m.author_name;
}

/**
 * Conversation of a request. `basePath` is the request API path (student or admin), `side` the viewer.
 * Opening the thread marks the other side's messages as read.
 */
export function MessageThread({
  basePath,
  side,
  canPost,
  respondMode = false,
  invalidate,
}: {
  basePath: string;
  side: "STUDENT" | "STAFF";
  canPost: boolean;
  /** Student answering an information request: posts to /respond (resumes the review). */
  respondMode?: boolean;
  invalidate: string[];
}) {
  const { locale, t } = useI18n();
  const refresh = useInvalidate();
  const messages = useApiQuery<RequestMessage[]>(`${basePath}/messages`);
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [sending, setSending] = useState(false);

  const unreadFromOther = messages.data?.some((m) => m.author_side !== side && !m.read_at) ?? false;
  useEffect(() => {
    if (!unreadFromOther) return;
    api(`${basePath}/messages/read`, { method: "POST" })
      .then(() => refresh(invalidate))
      .catch(() => undefined);
  }, [unreadFromOther, basePath, refresh, invalidate]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!body.trim()) {
      toast.error(t("errors.message_required"));
      return;
    }
    setSending(true);
    try {
      await api(`${basePath}/${respondMode ? "respond" : "messages"}`, {
        method: "POST",
        body: buildMessageForm(body, files),
      });
      setBody("");
      setFiles([]);
      toast.success(t(respondMode ? "requests.responded" : "requests.messageSent"));
      await refresh([`${basePath}`, ...invalidate]);
    } catch (err) {
      toast.error(errorMessage(t, err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-4">
      <QueryState isPending={messages.isPending} error={messages.error} onRetry={() => messages.refetch()}>
        {messages.data?.length ? (
          <ul className="space-y-3" data-testid="message-list">
            {messages.data.map((m) => {
              const mine = m.author_side === side;
              return (
                <li
                  key={m.id}
                  data-kind={m.kind}
                  className={cn(
                    "max-w-[85%] rounded-lg border p-3 text-sm",
                    mine ? "ms-auto bg-primary/5" : "me-auto bg-muted/40",
                    m.kind === "INFORMATION_REQUEST" && "border-amber-400",
                  )}
                >
                  <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{messageTitle(m, side, t)}</span>
                    <span>{formatDateTime(m.created_at, locale)}</span>
                    {m.kind === "INFORMATION_REQUEST" && (
                      <Badge className={TONE_CLASSES.warning}>{t("requests.informationRequest")}</Badge>
                    )}
                    {m.kind === "INFORMATION_RESPONSE" && (
                      <Badge className={TONE_CLASSES.info}>{t("requests.informationResponse")}</Badge>
                    )}
                    {!mine && !m.read_at && <Badge variant="default">{t("requests.new")}</Badge>}
                  </div>
                  <p className="whitespace-pre-line" dir="auto" data-testid="message-body">
                    {m.body}
                  </p>
                  {m.attachments.length > 0 && (
                    <div className="mt-2">
                      <DocumentList basePath={basePath} documents={m.attachments} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState icon={MessageSquareIcon} text={t("requests.noMessages")} />
        )}
      </QueryState>

      {canPost && (
        <form onSubmit={onSubmit} className="space-y-3" data-testid={respondMode ? "respond-form" : "message-form"}>
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={t("requests.messagePlaceholder")}
            maxLength={5000}
            rows={3}
            aria-label={t("requests.messagePlaceholder")}
            data-testid="message-input"
          />
          <div className="flex flex-wrap items-start justify-between gap-3">
            <FilePicker files={files} onChange={setFiles} testId="message-files" />
            <Button type="submit" disabled={sending} data-testid="message-send">
              <SendIcon className="rtl:-scale-x-100" />
              {t(respondMode ? "requests.respondSubmit" : "requests.send")}
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

/** Snapshot of the request: enrollment data, requested documents, the student's texts. */
export function RequestInfo({ request }: { request: RequestDetail }) {
  const { locale, t } = useI18n();
  const rows: [TranslationKey, string][] = [
    ["requests.year", request.academic_year.label],
    ["requests.category", localized(request.branch.category.name_i18n, locale)],
    ["requests.branch", localized(request.branch.name_i18n, locale)],
    ["requests.level", localized(request.study_level.name_i18n, locale)],
    ["requests.submittedAt", formatDateTime(request.submitted_at, locale)],
  ];
  return (
    <div className="space-y-4 text-sm">
      <dl className="grid gap-3 sm:grid-cols-3">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-muted-foreground">{t(label)}</dt>
            <dd className="font-medium">{value}</dd>
          </div>
        ))}
      </dl>
      <div>
        <p className="mb-1 text-muted-foreground">{t("requests.documentsToRequest")}</p>
        <ul className="space-y-1" data-testid="request-items">
          {request.items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{localized(item.document_type.name_i18n, locale)}</span>
              <span className="text-muted-foreground">× {item.quantity}</span>
              <Badge variant="outline">{t(`requests.delivery${item.document_type.delivery_mode}`)}</Badge>
            </li>
          ))}
        </ul>
      </div>
      {request.reason && (
        <div>
          <p className="text-muted-foreground">{t("requests.reason")}</p>
          <p className="whitespace-pre-line" dir="auto">
            {request.reason}
          </p>
        </div>
      )}
      {request.extra_info && (
        <div>
          <p className="text-muted-foreground">{t("requests.extraInfo")}</p>
          <p className="whitespace-pre-line" dir="auto">
            {request.extra_info}
          </p>
        </div>
      )}
      {request.status_reason && (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3" data-testid="status-reason">
          <p className="text-muted-foreground">{t("requests.statusReason")}</p>
          <p className="whitespace-pre-line" dir="auto">
            {request.status_reason}
          </p>
        </div>
      )}
    </div>
  );
}
