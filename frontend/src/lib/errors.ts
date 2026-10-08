import type { TFunction, TranslationKey } from "@/i18n/translate";
import { ApiError } from "./api/client";

/** Translates an API error code; unknown codes fall back to a generic message (never raw server text). */
export function errorMessage(t: TFunction, error: unknown): string {
  if (error instanceof ApiError) {
    const key = `errors.${error.code}` as TranslationKey;
    const translated = t(key);
    if (translated !== key) return translated;
    if (error.status === 403) return t("errors.forbidden");
    if (error.status === 404) return t("errors.not_found");
    if (error.status === 409) return t("errors.conflict");
  }
  return t("errors.generic");
}

/** Field-level messages from a 422 validation error, keyed by field name. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.code !== "validation_error" || !Array.isArray(error.details)) {
    return {};
  }
  const out: Record<string, string> = {};
  for (const item of error.details as { loc: (string | number)[]; msg: string }[]) {
    const field = item.loc.filter((p) => p !== "body").join(".");
    if (field && !out[field]) out[field] = item.msg;
  }
  return out;
}
