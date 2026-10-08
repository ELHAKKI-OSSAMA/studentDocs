"use client";

import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { ConstructionIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/i18n/client";
import type { TranslationKey } from "@/i18n/translate";
import { errorMessage } from "@/lib/errors";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function StatCard({
  label,
  value,
  icon: Icon,
  testId,
}: {
  label: string;
  value: ReactNode;
  icon: LucideIcon;
  testId?: string;
}) {
  return (
    <Card size="sm">
      <CardContent className="flex items-center gap-4">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-5" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm text-muted-foreground">{label}</p>
          <p className="text-2xl font-semibold tabular-nums" data-testid={testId}>
            {value}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

export function EmptyState({ icon: Icon, text }: { icon: LucideIcon; text: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center text-sm text-muted-foreground">
      <Icon className="size-8 opacity-50" aria-hidden />
      <p>{text}</p>
    </div>
  );
}

export function ComingSoon({ title }: { title: TranslationKey }) {
  const { t } = useI18n();
  return (
    <>
      <PageHeader title={t(title)} />
      <Card>
        <CardContent>
          <EmptyState icon={ConstructionIcon} text={t("common.comingSoonText")} />
        </CardContent>
      </Card>
    </>
  );
}

export function QueryState({
  isPending,
  error,
  onRetry,
  children,
}: {
  isPending: boolean;
  error: unknown;
  onRetry?: () => void;
  children: ReactNode;
}) {
  const { t } = useI18n();
  if (isPending) {
    return (
      <div className="space-y-2" aria-busy="true">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-2/3" />
      </div>
    );
  }
  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
          {errorMessage(t, error)}
          {onRetry && (
            <Button size="sm" variant="outline" onClick={onRetry}>
              {t("common.retry")}
            </Button>
          )}
        </AlertDescription>
      </Alert>
    );
  }
  return <>{children}</>;
}
