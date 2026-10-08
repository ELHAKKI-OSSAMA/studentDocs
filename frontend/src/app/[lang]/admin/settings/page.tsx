"use client";

import type { FormEvent } from "react";
import { toast } from "sonner";
import { AtSignIcon, Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { useI18n } from "@/i18n/client";
import { useApiMutation, useApiQuery } from "@/lib/api/hooks";
import type { EmailDomain } from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";

const PATH = "/admin/settings/email-domains";

export default function SettingsPage() {
  const { t } = useI18n();
  const domains = useApiQuery<EmailDomain[]>(PATH);
  const add = useApiMutation<string>((domain) => ({ path: PATH, method: "POST", body: { domain } }), ["/admin/"]);
  const remove = useApiMutation<string>((id) => ({ path: `${PATH}/${id}`, method: "DELETE" }), ["/admin/"]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget;
    const domain = String(new FormData(formEl).get("domain") ?? "").trim();
    try {
      await add.mutateAsync(domain);
      toast.success(t("common.created"));
      formEl.reset();
    } catch (err) {
      toast.error(errorMessage(t, err));
    }
  }

  return (
    <>
      <PageHeader title={t("settings.title")} />
      <Card>
        <CardHeader>
          <CardTitle>{t("settings.domainsTitle")}</CardTitle>
          <CardDescription>{t("settings.domainsText")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={onSubmit} className="flex max-w-md gap-2">
            <Input
              name="domain"
              aria-label={t("settings.domain")}
              placeholder={t("settings.domainPlaceholder")}
              required
              dir="ltr"
              maxLength={253}
            />
            <Button type="submit" disabled={add.isPending}>
              {t("common.add")}
            </Button>
          </form>
          <QueryState isPending={domains.isPending} error={domains.error} onRetry={() => domains.refetch()}>
            {domains.data?.length ? (
              <ul className="divide-y rounded-lg border" data-testid="domains">
                {domains.data.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-2 px-3 py-2">
                    <span dir="ltr" className="font-mono text-sm">@{d.domain}</span>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("common.delete")}
                      onClick={() =>
                        remove.mutateAsync(d.id).then(
                          () => toast.success(t("common.deleted")),
                          (err) => toast.error(errorMessage(t, err)),
                        )
                      }
                    >
                      <Trash2Icon />
                    </Button>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState icon={AtSignIcon} text={t("common.noData")} />
            )}
          </QueryState>
        </CardContent>
      </Card>
    </>
  );
}
