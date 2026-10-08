export const locales = ["fr", "en", "ar"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "fr";
/** Remembers the explicit language choice across visits (read by the routing proxy). */
export const LOCALE_COOKIE = "NEXT_LOCALE";

const rtlLocales: ReadonlySet<Locale> = new Set(["ar"]);

export function isLocale(value: string): value is Locale {
  return (locales as readonly string[]).includes(value);
}

export function direction(locale: Locale): "rtl" | "ltr" {
  return rtlLocales.has(locale) ? "rtl" : "ltr";
}

/**
 * Picks the best supported locale from an Accept-Language header.
 * Only the primary language subtag is considered ("ar-MA" -> "ar").
 */
export function negotiateLocale(acceptLanguage: string | null | undefined): Locale {
  if (!acceptLanguage) return defaultLocale;
  const candidates = acceptLanguage
    .split(",")
    .map((part, index) => {
      const [tag, ...params] = part.trim().split(";");
      const qParam = params.find((p) => p.trim().startsWith("q="));
      const q = qParam ? Number.parseFloat(qParam.trim().slice(2)) : 1;
      return { lang: tag.trim().toLowerCase().split("-")[0], q: Number.isNaN(q) ? 0 : q, index };
    })
    .filter((c) => c.lang && c.q > 0)
    .sort((a, b) => b.q - a.q || a.index - b.index);
  for (const c of candidates) {
    if (isLocale(c.lang)) return c.lang;
  }
  return defaultLocale;
}

/** Returns the locale prefix of a pathname, or null if it has none. */
export function localeFromPathname(pathname: string): Locale | null {
  const first = pathname.split("/")[1] ?? "";
  return isLocale(first) ? first : null;
}
