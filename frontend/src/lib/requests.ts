/**
 * Pure helpers for the request screens. Business rules stay enforced by the backend; these only
 * give early feedback and build the exact payloads the API expects.
 */
import type { TranslationKey } from "@/i18n/translate";
import type { DocumentType, RequestStatus, ScanStatus } from "@/lib/api/types";

/** Mirrors the backend upload policy (app/core/config.py + app/documents/validation.py). */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const ALLOWED_MIME_TYPES = ["application/pdf", "image/png", "image/jpeg"] as const;
export const FILE_ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";

/** Transitions whose comment is mandatory on the backend (workflow.py `requires_comment`). */
const COMMENT_REQUIRED: ReadonlySet<RequestStatus> = new Set(["NEEDS_INFORMATION", "REJECTED", "CANCELLED"]);

export function commentRequired(target: RequestStatus): boolean {
  return COMMENT_REQUIRED.has(target);
}

/** Destructive actions are rendered differently (and asked for confirmation with a reason). */
export function isDestructive(target: RequestStatus): boolean {
  return target === "REJECTED" || target === "CANCELLED";
}

export type StatusTone = "neutral" | "info" | "warning" | "success" | "danger";

export function statusTone(status: RequestStatus): StatusTone {
  switch (status) {
    case "NEEDS_INFORMATION":
      return "warning";
    case "APPROVED":
    case "DOCUMENT_AVAILABLE":
    case "READY_FOR_PICKUP":
    case "COMPLETED":
      return "success";
    case "REJECTED":
    case "CANCELLED":
      return "danger";
    case "IN_REVIEW":
    case "PROCESSING":
      return "info";
    default:
      return "neutral";
  }
}

export function scanTone(status: ScanStatus): StatusTone {
  if (status === "CLEAN") return "success";
  if (status === "SCANNING") return "info";
  if (status === "INFECTED" || status === "ERROR") return "danger";
  return "warning";
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_RE.test(value);
}

const EXTENSIONS: Record<string, string> = { pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg" };
const DANGEROUS = new Set(["exe", "dll", "com", "scr", "msi", "bat", "cmd", "ps1", "vbs", "js", "jar", "sh", "hta", "lnk", "html", "htm", "svg", "php"]);

/**
 * Early client-side check before upload; returns an `errors.*` key or null. Only a convenience: the
 * backend re-checks everything from the content (magic bytes) and the antivirus scans every file.
 */
export function fileProblem(file: File): TranslationKey | null {
  if (file.size === 0) return "errors.file_empty";
  if (file.size > MAX_UPLOAD_BYTES) return "errors.file_too_large";
  const parts = file.name.toLowerCase().split(".");
  if (parts.slice(1).some((p) => DANGEROUS.has(p.trim()))) return "errors.file_name_not_allowed";
  const expected = parts.length > 1 ? EXTENSIONS[parts[parts.length - 1]] : undefined;
  if (!expected) return "errors.file_type_not_allowed";
  if (file.type && !(ALLOWED_MIME_TYPES as readonly string[]).includes(file.type)) {
    return "errors.file_type_not_allowed";
  }
  if (file.type && file.type !== expected) return "errors.file_mime_mismatch";
  return null;
}

export type Selection = Record<string, { quantity: number; file?: File | null }>;

export type NewRequestDraft = {
  enrollmentId: string;
  selection: Selection;
  reason?: string;
  extraInfo?: string;
};

/** Validates the draft against the catalog rules; returns translation keys (empty = valid). */
export function validateDraft(draft: NewRequestDraft, types: DocumentType[]): TranslationKey[] {
  const problems = new Set<TranslationKey>();
  if (!draft.enrollmentId) problems.add("requests.selectEnrollment");
  const chosen = Object.keys(draft.selection);
  if (!chosen.length) problems.add("requests.selectAtLeastOne");
  for (const id of chosen) {
    const type = types.find((t) => t.id === id);
    if (!type) {
      problems.add("errors.document_type_not_allowed");
      continue;
    }
    const { quantity, file } = draft.selection[id];
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > type.max_quantity) {
      problems.add("errors.quantity_exceeded");
    }
    if (type.requires_attachment && !file) problems.add("requests.missingAttachment");
    if (file) {
      const problem = fileProblem(file);
      if (problem) problems.add(problem);
    }
  }
  return [...problems];
}

/** Multipart body for POST /requests: a JSON `payload` part plus one `attachment:<type id>` per file. */
export function buildRequestForm(draft: NewRequestDraft): FormData {
  const form = new FormData();
  const payload = {
    enrollment_id: draft.enrollmentId,
    items: Object.entries(draft.selection).map(([id, { quantity }]) => ({ document_type_id: id, quantity })),
    reason: draft.reason?.trim() || null,
    extra_info: draft.extraInfo?.trim() || null,
  };
  form.append("payload", JSON.stringify(payload));
  for (const [id, { file }] of Object.entries(draft.selection)) {
    if (file) form.append(`attachment:${id}`, file, file.name);
  }
  return form;
}

/** Multipart body for messages / information responses: `body` + `files`. */
export function buildMessageForm(body: string, files: File[]): FormData {
  const form = new FormData();
  form.append("body", body);
  for (const file of files) form.append("files", file, file.name);
  return form;
}

export function formatBytes(bytes: number, locale: string): string {
  const units = ["B", "KB", "MB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${new Intl.NumberFormat(locale, { maximumFractionDigits: unit ? 1 : 0 }).format(value)} ${units[unit]}`;
}

export function formatDateTime(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function formatDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium" }).format(new Date(iso));
}
