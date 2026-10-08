import type { Locale } from "./config";
import type fr from "./dictionaries/fr.json";

export type Dictionary = typeof fr;

type Leaves<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : Leaves<T[K], `${P}${K}.`>;
}[keyof T & string];

/** Every valid translation key, e.g. "auth.loginTitle". A typo is a compile error. */
export type TranslationKey = Leaves<Dictionary>;

export type TFunction = (key: TranslationKey, params?: Record<string, string | number>) => string;

export function lookup(dict: Dictionary, key: string): string | undefined {
  let node: unknown = dict;
  for (const part of key.split(".")) {
    if (typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string" ? node : undefined;
}

export function createT(dict: Dictionary): TFunction {
  return (key, params) => {
    const template = lookup(dict, key) ?? key;
    if (!params) return template;
    return template.replace(/\{(\w+)\}/g, (match, name: string) =>
      name in params ? String(params[name]) : match,
    );
  };
}

export type I18nText = { fr: string; en?: string | null; ar?: string | null };

/** Picks the label in the current locale, falling back to French (always present). */
export function localized(text: I18nText | null | undefined, locale: Locale): string {
  if (!text) return "";
  return text[locale] || text.fr;
}
