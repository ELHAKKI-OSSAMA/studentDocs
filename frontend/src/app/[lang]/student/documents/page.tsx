"use client";

import Link from "next/link";
import { FolderOpenIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { DocumentList, ScanNotice } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { useApiQuery } from "@/lib/api/hooks";
import type { IssuedDocument } from "@/lib/api/types";

/** Documents issued by the administration, once made available (the API hides the others). */
export default function DocumentsPage() {
  const { locale, t } = useI18n();
  const documents = useApiQuery<IssuedDocument[]>("/requests/documents");
  const byRequest = new Map<string, IssuedDocument[]>();
  for (const doc of documents.data ?? []) {
    byRequest.set(doc.request_id, [...(byRequest.get(doc.request_id) ?? []), doc]);
  }

  return (
    <>
      <PageHeader title={t("requests.documentsTitle")} />
      <Card>
        <CardContent className="space-y-6">
          <QueryState isPending={documents.isPending} error={documents.error} onRetry={() => documents.refetch()}>
            {byRequest.size ? (
              <div className="space-y-6" data-testid="issued-documents">
                {[...byRequest.entries()].map(([requestId, docs]) => (
                  <section key={requestId} className="space-y-2">
                    <Link
                      href={`/${locale}/student/requests/${requestId}`}
                      className="font-mono text-sm font-medium text-primary hover:underline"
                      dir="ltr"
                    >
                      {docs[0].reference}
                    </Link>
                    <DocumentList basePath={`/requests/${requestId}`} documents={docs} />
                  </section>
                ))}
              </div>
            ) : (
              <EmptyState icon={FolderOpenIcon} text={t("requests.documentsEmpty")} />
            )}
          </QueryState>
          <ScanNotice />
        </CardContent>
      </Card>
    </>
  );
}
