"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { Locale } from "@/i18n/config";
import { direction } from "@/i18n/config";
import { I18nProvider } from "@/i18n/client";
import type { Dictionary } from "@/i18n/translate";
import { ApiError } from "@/lib/api/client";

export function Providers({
  locale,
  dictionary,
  children,
}: {
  locale: Locale;
  dictionary: Dictionary;
  children: ReactNode;
}) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            // Auth / permission errors are final; only transient failures are retried.
            retry: (count, error) =>
              count < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <I18nProvider locale={locale} dictionary={dictionary}>
        <TooltipProvider>
          {children}
          <Toaster position={direction(locale) === "rtl" ? "bottom-left" : "bottom-right"} richColors />
        </TooltipProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}
