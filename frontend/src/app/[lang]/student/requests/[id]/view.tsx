"use client";

import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { ArrowLeftIcon, CircleAlertIcon, PackageCheckIcon } from "lucide-react";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader, QueryState } from "@/components/page";
import {
  DocumentList,
  hasPendingScan,
  MessageThread,
  RequestInfo,
  SCAN_POLL_MS,
  ScanNotice,
  StatusBadge,
  Timeline,
} from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { api, ApiError } from "@/lib/api/client";
import { useApiQuery, useInvalidate } from "@/lib/api/hooks";
import type { RequestDetail } from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { isUuid } from "@/lib/requests";

const LISTS = ["/requests", "/notifications"];

function CancelButton({ request }: { request: RequestDetail }) {
  const { t } = useI18n();
  const refresh = useInvalidate();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function confirm() {
    setBusy(true);
    try {
      await api(`/requests/${request.id}/cancel`, { method: "POST" });
      toast.success(t("requests.cancelled"));
      setOpen(false);
      await refresh(LISTS);
    } catch (err) {
      toast.error(errorMessage(t, err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="destructive" onClick={() => setOpen(true)} data-testid="cancel-request">
        {t("requests.cancel")}
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("requests.cancelConfirmTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("requests.cancelConfirmText")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("requests.keep")}</AlertDialogCancel>
            <Button variant="destructive" onClick={confirm} disabled={busy} data-testid="confirm-cancel">
              {t("requests.cancel")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export function RequestView({ id }: { id: string }) {
  const { locale, t } = useI18n();
  const valid = isUuid(id);
  const request = useApiQuery<RequestDetail>(`/requests/${id}`, undefined, {
    enabled: valid,
    // The worker updates scan results asynchronously: poll only while a file is being scanned.
    refetchInterval: (data) => (hasPendingScan(data?.documents) ? SCAN_POLL_MS : false),
  });
  const back = (
    <Link href={`/${locale}/student/requests`} className={buttonVariants({ variant: "ghost", size: "sm" })}>
      <ArrowLeftIcon className="rtl:-scale-x-100" />
      {t("requests.myRequestsTitle")}
    </Link>
  );

  // An invalid reference never reaches the API: it is the same "not found" as another student's request.
  const error = valid ? request.error : new ApiError(404, "not_found", "");
  const data = request.data;

  return (
    <>
      <div className="mb-2">{back}</div>
      <QueryState isPending={valid && request.isPending} error={error} onRetry={() => request.refetch()}>
        {data && (
          <>
            <PageHeader
              title={t("requests.detailTitle", { reference: data.reference })}
              description={<StatusBadge status={data.status} />}
              actions={data.can_cancel ? <CancelButton request={data} /> : undefined}
            />
            {data.status === "NEEDS_INFORMATION" && (
              <Alert className="mb-6 border-amber-400" data-testid="information-needed">
                <CircleAlertIcon />
                <AlertTitle>{t("requests.respondTitle")}</AlertTitle>
                <AlertDescription>{t("requests.respondHint")}</AlertDescription>
              </Alert>
            )}
            {data.status === "READY_FOR_PICKUP" && (
              <Alert className="mb-6" data-testid="pickup-notice">
                <PackageCheckIcon />
                <AlertDescription>{t("requests.pickupNotice")}</AlertDescription>
              </Alert>
            )}
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="flex flex-col gap-6 lg:col-span-2">
                <Card>
                  <CardContent className="pt-6">
                    <RequestInfo request={data} />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>{t("requests.documents")}</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <DocumentList
                      basePath={`/requests/${data.id}`}
                      documents={data.documents.filter((d) => d.kind !== "MESSAGE")}
                    />
                    <ScanNotice />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>{t("requests.messages")}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <MessageThread
                      basePath={`/requests/${data.id}`}
                      side="STUDENT"
                      canPost={data.can_respond || data.can_message}
                      respondMode={data.can_respond}
                      invalidate={LISTS}
                    />
                  </CardContent>
                </Card>
              </div>
              <Card className="h-fit">
                <CardHeader>
                  <CardTitle>{t("requests.timeline")}</CardTitle>
                </CardHeader>
                <CardContent>
                  <Timeline history={data.history} />
                </CardContent>
              </Card>
            </div>
          </>
        )}
      </QueryState>
    </>
  );
}
