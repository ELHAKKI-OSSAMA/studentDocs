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
import type { RequestDetail, RequestStatus } from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { commentRequired, isDestructive } from "@/lib/requests";

export const ADMIN_REQUEST_LISTS = ["/admin/requests", "/admin/dashboard", "/notifications"];

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
  const required = commentRequired(target);

  async function confirm() {
    if (required && !comment.trim()) {
      setError(t("errors.message_required"));
      return;
    }
    setBusy(true);
    try {
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
