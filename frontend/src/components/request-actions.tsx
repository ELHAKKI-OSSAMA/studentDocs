"use client";

/** Status actions of the admin request screen: only transitions computed by the backend are offered. */

import { useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/i18n/client";
import { api } from "@/lib/api/client";
import { useInvalidate } from "@/lib/api/hooks";
import { FilePicker } from "@/components/requests";
import type { RequestDetail, RequestDocument, RequestStatus } from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { commentRequired, isDestructive } from "@/lib/requests";

export const ADMIN_REQUEST_LISTS = ["/admin/requests", "/admin/dashboard", "/notifications"];

const SCAN_WAIT_MS = 90_000;

/** Delivery that needs a final document scanned CLEAN (same rule as the backend state machine). */
function needsIssuedDocument(request: RequestDetail, target: RequestStatus): boolean {
  if (target === "DOCUMENT_AVAILABLE") return true;
  return target === "READY_FOR_PICKUP" && request.items.some((i) => i.document_type.delivery_mode === "DIGITAL");
}

function cleanIssued(docs: RequestDocument[]): RequestDocument[] {
  return docs.filter((d) => d.kind === "ISSUED" && d.scan_status === "CLEAN");
}

/** Waits until the antivirus has a verdict on every final document (they are unusable while SCANNING). */
async function waitForScans(requestId: string): Promise<RequestDetail> {
  const deadline = Date.now() + SCAN_WAIT_MS;
  for (;;) {
    const detail = await api<RequestDetail>(`/admin/requests/${requestId}`);
    const issued = detail.documents.filter((d) => d.kind === "ISSUED");
    if (!issued.some((d) => d.scan_status === "SCANNING" || d.scan_status === "NOT_SCANNED")) return detail;
    if (Date.now() > deadline) return detail;
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}

/** Transition dialog: the comment is visible to the student and mandatory where the backend requires it. */
function TransitionDialog({
  request,
  target,
  onClose,
}: {
  request: RequestDetail;
  target: RequestStatus;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const refresh = useInvalidate();
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"upload" | "scan" | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const required = commentRequired(target);
  // The final document can be added right here instead of the Documents section.
  const askFile = needsIssuedDocument(request, target) && cleanIssued(request.documents).length === 0;

  async function confirm() {
    if (required && !comment.trim()) {
      setError(t("errors.message_required"));
      return;
    }
    if (askFile && !files.length && !request.documents.some((d) => d.kind === "ISSUED")) {
      setError(t("errors.issued_document_required"));
      return;
    }
    setBusy(true);
    try {
      if (askFile && files.length) {
        setPhase("upload");
        const form = new FormData();
        for (const f of files) form.append("files", f, f.name);
        await api(`/admin/requests/${request.id}/documents`, { method: "POST", body: form });
        setFiles([]);
      }
      if (askFile) {
        setPhase("scan");
        const detail = await waitForScans(request.id);
        await refresh(ADMIN_REQUEST_LISTS);
        if (!cleanIssued(detail.documents).length) {
          const issued = detail.documents.filter((d) => d.kind === "ISSUED");
          const rejected = issued.some((d) => d.scan_status === "INFECTED" || d.scan_status === "ERROR");
          setError(t(rejected ? "requests.issuedRejected" : "requests.issuedStillScanning"));
          return;
        }
      }
      setPhase(null);
      await api(`/admin/requests/${request.id}/transitions`, {
        method: "POST",
        body: { to_status: target, comment: comment.trim() || null },
      });
      toast.success(t("requests.statusChanged", { status: t(`status.${target}`) }));
      onClose();
      await refresh(ADMIN_REQUEST_LISTS);
    } catch (err) {
      setError(errorMessage(t, err));
    } finally {
      setBusy(false);
      setPhase(null);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t(`action.${target}`)}</DialogTitle>
          <DialogDescription>{t(required ? "requests.commentRequired" : "requests.commentOptional")}</DialogDescription>
        </DialogHeader>
        <Textarea
          value={comment}
          onChange={(e) => {
            setComment(e.target.value);
            setError(null);
          }}
          maxLength={2000}
          rows={4}
          aria-label={t("requests.comment")}
          aria-invalid={!!error}
          data-testid="transition-comment"
        />
        {askFile && (
          <div className="space-y-2 rounded-lg border border-dashed p-3" data-testid="transition-issued-upload">
            <p className="text-sm font-medium">{t("requests.uploadIssued")}</p>
            <p className="text-xs text-muted-foreground">{t("requests.issuedInDialogHint")}</p>
            <FilePicker
              files={files}
              onChange={(f) => {
                setFiles(f);
                setError(null);
              }}
              testId="transition-issued-input"
            />
          </div>
        )}
        {phase && (
          <p className="text-sm text-muted-foreground" data-testid="transition-progress" role="status">
            {t(phase === "upload" ? "requests.uploading" : "scan.receivedScanning")}
          </p>
        )}
        {error && (
          <Alert variant="destructive">
            <AlertDescription data-testid="transition-error">{error}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant={isDestructive(target) ? "destructive" : "default"}
            onClick={confirm}
            disabled={busy}
            data-testid="confirm-transition"
          >
            {t("requests.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function RequestActions({ request }: { request: RequestDetail }) {
  const { t } = useI18n();
  const [target, setTarget] = useState<RequestStatus | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("requests.actions")}</CardTitle>
      </CardHeader>
      <CardContent>
        {/* Only the transitions computed by the backend for this request and this user are offered. */}
        {request.available_transitions.length ? (
          <div className="flex flex-wrap gap-2" data-testid="transition-buttons">
            {request.available_transitions.map((s) => (
              <Button
                key={s}
                variant={isDestructive(s) ? "destructive" : s === "APPROVED" ? "default" : "outline"}
                onClick={() => setTarget(s)}
                data-testid={`transition-${s}`}
              >
                {t(`action.${s}`)}
              </Button>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("requests.noActions")}</p>
        )}
        {target && <TransitionDialog request={request} target={target} onClose={() => setTarget(null)} />}
      </CardContent>
    </Card>
  );
}
