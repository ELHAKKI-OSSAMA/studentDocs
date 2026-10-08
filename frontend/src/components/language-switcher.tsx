"use client";

import { LanguagesIcon } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { LOCALE_COOKIE, locales, type Locale } from "@/i18n/config";
import { useI18n } from "@/i18n/client";
import { api } from "@/lib/api/client";
import { meKey } from "@/lib/api/hooks";

export const languageNames: Record<Locale, string> = { fr: "Français", en: "English", ar: "العربية" };

export function switchLocalePath(pathname: string, locale: Locale): string {
  const parts = pathname.split("/");
  parts[1] = locale;
  return parts.join("/") || `/${locale}`;
}

export function LanguageSwitcher({ signedIn = false }: { signedIn?: boolean }) {
  const { locale, t } = useI18n();
  const pathname = usePathname();
  const router = useRouter();
  const qc = useQueryClient();

  async function change(next: string) {
    const target = next as Locale;
    if (target === locale) return;
    document.cookie = `${LOCALE_COOKIE}=${target}; path=/; max-age=31536000; samesite=lax`;
    if (signedIn) {
      // Persist the preference on the account (used for emails); UI switch does not depend on it.
      await api("/auth/me", { method: "PATCH", body: { locale: target } }).catch(() => undefined);
      qc.invalidateQueries({ queryKey: meKey });
    }
    router.push(`${switchLocalePath(pathname, target)}${window.location.search}`);
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="sm" aria-label={t("student.preferredLanguage")} />}
        data-testid="language-switcher"
      >
        <LanguagesIcon />
        <span>{languageNames[locale]}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuRadioGroup value={locale} onValueChange={change}>
          {locales.map((l) => (
            <DropdownMenuRadioItem key={l} value={l} lang={l} data-testid={`lang-${l}`}>
              {languageNames[l]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
