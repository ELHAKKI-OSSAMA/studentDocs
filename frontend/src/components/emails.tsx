"use client";

/** Building blocks of the inbound email review screens. */

import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/i18n/client";
import type { AuthVerdict, EmailCaseStatus, ReviewConfidence } from "@/lib/api/types";
import type { StatusTone } from "@/lib/requests";

const TONES: Record<StatusTone, string> = {
  neutral: "bg-muted text-foreground",
  info: "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200",
  warning: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  success: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  danger: "bg-destructive/10 text-destructive",
};

export function emailStatusTone(status: EmailCaseStatus): StatusTone {
  switch (status) {
    case "NEEDS_REVIEW":
      return "warning";
    case "CONVERTED":
    case "LINKED":
      return "success";
    case "FAILED":
      return "danger";
    case "NEW":
    case "AI_PROCESSING":
      return "info";
    default:
      return "neutral";
  }
}

export function EmailStatusBadge({ status }: { status: EmailCaseStatus }) {
  const { t } = useI18n();
  return (
    <Badge className={TONES[emailStatusTone(status)]} data-testid="email-status" data-status={status}>
      {t(`emailStatus.${status}`)}
    </Badge>
  );
}

/** Completeness level computed by rules (not a probability, never an authorization). */
export function ConfidenceBadge({ level }: { level: ReviewConfidence }) {
  const { t } = useI18n();
  const tone: StatusTone = level === "HIGH" ? "success" : level === "MEDIUM" ? "info" : "warning";
  return (
    <Badge
      variant="outline"
      className={TONES[tone]}
      title={t("reviewConfidence.hint")}
      data-testid="review-confidence"
      data-level={level}
    >
      {t(`reviewConfidence.${level}`)}
    </Badge>
  );
}

export function AuthBadge({ verdict }: { verdict: AuthVerdict }) {
  const { t } = useI18n();
  const tone: StatusTone = verdict === "PASS" ? "success" : verdict === "FAIL" || verdict === "CONTRADICTORY" ? "danger" : "neutral";
  return (
    <Badge className={TONES[tone]} data-testid="email-auth" data-verdict={verdict}>
      {t(`emailAuth.${verdict}`)}
    </Badge>
  );
}

/**
 * Email HTML, already sanitized by the server (nh3 allow-list), shown in a sandboxed iframe: an empty
 * `sandbox` attribute disables scripts, forms, popups, navigation and gives the frame an opaque origin;
 * the CSP forbids every network load (no remote image, font or stylesheet).
 */
export function SandboxedHtml({ html, title }: { html: string; title: string }) {
  const doc =
    `<!doctype html><html><head><meta charset="utf-8">` +
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">` +
    `<style>body{font:14px/1.5 system-ui,sans-serif;margin:12px;color:#111;word-break:break-word}` +
    `table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:4px}</style></head>` +
    `<body dir="auto">${html}</body></html>`;
  return (
    <iframe
      sandbox=""
      srcDoc={doc}
      title={title}
      referrerPolicy="no-referrer"
      className="h-80 w-full rounded-md border bg-white"
      data-testid="email-html-frame"
    />
  );
}
