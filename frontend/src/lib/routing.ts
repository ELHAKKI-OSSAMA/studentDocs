import { isLocale, localeFromPathname, negotiateLocale, type Locale } from "@/i18n/config";

export type SessionArea = "student" | "admin";

type RouteInput = {
  pathname: string;
  search?: string;
  localeCookie?: string | null;
  acceptLanguage?: string | null;
  /** Non-secret hint cookie set at login; real authorization always happens in the API. */
  sessionArea?: string | null;
};

const PROTECTED: ReadonlySet<string> = new Set(["student", "admin"]);
const GUEST_ONLY: ReadonlySet<string> = new Set(["login", "register"]);

function area(value: string | null | undefined): SessionArea | null {
  return value === "student" || value === "admin" ? value : null;
}

/** Returns the URL to redirect to, or null when the request can proceed. */
export function resolveRedirect({
  pathname,
  search = "",
  localeCookie,
  acceptLanguage,
  sessionArea,
}: RouteInput): string | null {
  const locale = localeFromPathname(pathname);
  if (!locale) {
    const preferred: Locale =
      localeCookie && isLocale(localeCookie) ? localeCookie : negotiateLocale(acceptLanguage);
    return `/${preferred}${pathname === "/" ? "" : pathname}${search}`;
  }

  const section = pathname.split("/")[2] ?? "";
  const current = area(sessionArea);
  if (PROTECTED.has(section) && !current) {
    return `/${locale}/login?next=${encodeURIComponent(pathname + search)}`;
  }
  if (section === "admin" && current === "student") return `/${locale}/student`;
  if (section === "student" && current === "admin") return `/${locale}/admin`;
  if (GUEST_ONLY.has(section) && current) return `/${locale}/${current}`;
  return null;
}

/** Only same-app, locale-prefixed paths are accepted as post-login destinations (no open redirect). */
export function safeNext(next: string | null | undefined, locale: Locale, fallback: string): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return fallback;
  return localeFromPathname(next) ? next : `/${locale}${next}`;
}
