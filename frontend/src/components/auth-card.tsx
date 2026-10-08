"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { GraduationCapIcon } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LanguageSwitcher } from "@/components/language-switcher";
import { useI18n } from "@/i18n/client";

export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const { locale, t } = useI18n();
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex items-center justify-between px-4 py-3 md:px-8">
        <Link href={`/${locale}`} className="flex items-center gap-2 font-semibold text-primary">
          <GraduationCapIcon className="size-5" aria-hidden />
          {t("app.name")}
        </Link>
        <LanguageSwitcher />
      </header>
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <Card className="w-full max-w-md">
          <CardHeader>
            <CardTitle className="text-xl">
              <h1>{title}</h1>
            </CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {children}
            {footer && <div className="text-center text-sm text-muted-foreground">{footer}</div>}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${id}-hint`} className="text-xs text-muted-foreground">
            {hint}
          </p>
        )
      )}
    </div>
  );
}
