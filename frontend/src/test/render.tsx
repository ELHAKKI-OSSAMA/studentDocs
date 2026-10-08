import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { I18nProvider } from "@/i18n/client";
import { direction, type Locale } from "@/i18n/config";
import type { Dictionary } from "@/i18n/translate";
import fr from "@/i18n/dictionaries/fr.json";
import en from "@/i18n/dictionaries/en.json";
import ar from "@/i18n/dictionaries/ar.json";

const DICTS: Record<Locale, Dictionary> = { fr, en, ar };

// jsdom has no PointerEvent; Base UI controls (checkbox, dialog) dispatch it on click.
if (typeof window !== "undefined" && !("PointerEvent" in window)) {
  class PointerEventPolyfill extends MouseEvent {
    readonly pointerType: string;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerType = init.pointerType ?? "mouse";
    }
  }
  Object.assign(window, { PointerEvent: PointerEventPolyfill });
}

/** Renders with the real providers (i18n + react-query) and the locale's direction, like the app layout. */
export function renderWithProviders(ui: ReactElement, locale: Locale = "fr") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider locale={locale} dictionary={DICTS[locale]}>
        <div dir={direction(locale)} lang={locale} data-testid="root">
          {ui}
        </div>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

export type Route = { method?: string; path: string | RegExp; status?: number; body?: unknown };
export type Call = { method: string; url: string; init: RequestInit };

/** Test double for `fetch` driven by a route table; records every call for assertions. */
export function stubFetch(routes: Route[]) {
  const calls: Call[] = [];
  const fetchMock = async (input: string | URL, init: RequestInit = {}) => {
    const url = String(input);
    const method = (init.method ?? "GET").toUpperCase();
    calls.push({ method, url, init });
    const path = url.split("?")[0];
    const route = routes.find(
      (r) => (r.method ?? "GET") === method && (typeof r.path === "string" ? r.path === path : r.path.test(path)),
    );
    if (!route) {
      return new Response(JSON.stringify({ error: { code: "not_found", message: "" } }), { status: 404 });
    }
    const status = route.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(route.body ?? {}), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return { fetchMock, calls };
}
