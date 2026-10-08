"use client";

import Link from "next/link";
import { useState } from "react";
import { InboxIcon, PlusIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { Pager } from "@/components/pager";
import { StatusBadge } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { localized } from "@/i18n/translate";
import { useApiQuery } from "@/lib/api/hooks";
import { REQUEST_STATUSES, type Page, type RequestListItem } from "@/lib/api/types";
import { formatDate } from "@/lib/requests";

const LIMIT = 20;

export default function MyRequestsPage() {
  const { locale, t } = useI18n();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const requests = useApiQuery<Page<RequestListItem>>("/requests", { status, limit: LIMIT, offset });

  return (
    <>
      <PageHeader
        title={t("requests.myRequestsTitle")}
        actions={
          <Link href={`/${locale}/student/new-request`} className={buttonVariants()}>
            <PlusIcon />
            {t("student.newRequestCta")}
          </Link>
        }
      />
      <Card>
        <CardContent className="space-y-4">
          <div className="max-w-xs">
            <NativeSelect
              aria-label={t("common.status")}
              value={status}
              data-testid="status-filter"
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">{t("requests.allStatuses")}</option>
              {REQUEST_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`status.${s}`)}
                </option>
              ))}
            </NativeSelect>
          </div>
          <QueryState isPending={requests.isPending} error={requests.error} onRetry={() => requests.refetch()}>
            {requests.data?.items.length ? (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("requests.reference")}</TableHead>
                      <TableHead>{t("requests.documents")}</TableHead>
                      <TableHead>{t("common.status")}</TableHead>
                      <TableHead>{t("requests.date")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody data-testid="requests-table">
                    {requests.data.items.map((r) => (
                      <TableRow key={r.id} data-reference={r.reference}>
                        <TableCell>
                          <Link
                            href={`/${locale}/student/requests/${r.id}`}
                            className="font-mono font-medium text-primary hover:underline"
                            dir="ltr"
                          >
                            {r.reference}
                          </Link>
                          {r.unread_messages > 0 && (
                            <Badge className="ms-2" data-testid="unread-badge">
                              {t("requests.unread", { n: r.unread_messages })}
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="max-w-64 truncate">
                          {r.items.map((i) => localized(i.document_type.name_i18n, locale)).join(", ")}
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={r.status} />
                        </TableCell>
                        <TableCell className="text-muted-foreground">{formatDate(r.created_at, locale)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pager total={requests.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
              </>
            ) : (
              <EmptyState icon={InboxIcon} text={t("requests.empty")} />
            )}
          </QueryState>
        </CardContent>
      </Card>
    </>
  );
}
