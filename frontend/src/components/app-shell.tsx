"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { GraduationCapIcon, LogOutIcon, MenuIcon, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { LanguageSwitcher } from "@/components/language-switcher";
import { NotificationBell, type Area } from "@/components/notifications";
import { useI18n } from "@/i18n/client";
import type { TranslationKey } from "@/i18n/translate";
import { direction } from "@/i18n/config";
import { api } from "@/lib/api/client";
import type { Me } from "@/lib/api/types";
import { cn } from "cn";

export type NavItem = {
  href: string; // relative to /{locale}
  label: TranslationKey;
  icon: LucideIcon;
  permission?: string;
  exact?: boolean;
};
export type NavSection = { title?: TranslationKey; items: NavItem[] };

function NavLinks({ sections, me, onNavigate }: { sections: NavSection[]; me: Me; onNavigate?: () => void }) {
  const { locale, t } = useI18n();
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-5 px-3 py-4" aria-label="Main">
      {sections.map((section, i) => {
        const items = section.items.filter((it) => !it.permission || me.permissions.includes(it.permission));
        if (!items.length) return null;
        return (
          <div key={section.title ?? i} className="flex flex-col gap-0.5">
            {section.title && (
              <p className="px-3 pb-1 text-xs font-medium tracking-wide text-sidebar-foreground/60 uppercase">
                {t(section.title)}
              </p>
            )}
            {items.map((item) => {
              const href = `/${locale}${item.href}`;
              const active = item.exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-sidebar-foreground/85 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                    active && "bg-sidebar-accent font-medium text-sidebar-accent-foreground",
                  )}
                >
                  <Icon className="size-4 shrink-0" aria-hidden />
                  <span className="truncate">{t(item.label)}</span>
                </Link>
              );
            })}
          </div>
        );
      })}
    </nav>
  );
}

function Brand({ subtitle }: { subtitle: TranslationKey }) {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2.5 px-6 py-5">
      <span className="grid size-9 place-items-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
        <GraduationCapIcon className="size-5" aria-hidden />
      </span>
      <div className="leading-tight">
        <p className="font-semibold text-sidebar-foreground">{t("app.name")}</p>
        <p className="text-xs text-sidebar-foreground/70">{t(subtitle)}</p>
      </div>
    </div>
  );
}

export function AppShell({
  area,
  me,
  sections,
  subtitle,
  children,
}: {
  area: Area;
  me: Me;
  sections: NavSection[];
  subtitle: TranslationKey;
  children: ReactNode;
}) {
  const { locale, t } = useI18n();
  const router = useRouter();
  const qc = useQueryClient();
  const [mobileOpen, setMobileOpen] = useState(false);

  async function logout() {
    await api("/auth/logout", { method: "POST", noRefresh: true }).catch(() => undefined);
    qc.clear();
    router.replace(`/${locale}/login`);
  }

  const initials = `${me.first_name[0] ?? ""}${me.last_name[0] ?? ""}`.toUpperCase();

  return (
    <div className="flex min-h-svh">
      <aside className="sticky top-0 hidden h-svh w-64 shrink-0 flex-col overflow-y-auto bg-sidebar md:flex">
        <Brand subtitle={subtitle} />
        <NavLinks sections={sections} me={me} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/90 px-4 backdrop-blur md:px-6">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger render={<Button variant="ghost" size="icon" className="md:hidden" aria-label={t("common.openMenu")} />}>
              <MenuIcon />
            </SheetTrigger>
            <SheetContent side={direction(locale) === "rtl" ? "right" : "left"} className="w-72 bg-sidebar p-0">
              <SheetTitle className="sr-only">{t("app.name")}</SheetTitle>
              <Brand subtitle={subtitle} />
              <NavLinks sections={sections} me={me} onNavigate={() => setMobileOpen(false)} />
            </SheetContent>
          </Sheet>

          <div className="ms-auto flex items-center gap-1">
            <NotificationBell area={area} />
            <LanguageSwitcher signedIn />
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="ghost" className="gap-2 px-2" data-testid="user-menu" />}
              >
                <span className="grid size-7 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                  {initials}
                </span>
                <span className="hidden max-w-40 truncate text-sm sm:inline">
                  {me.first_name} {me.last_name}
                </span>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                {/* Base UI requires group labels to live inside a Menu.Group. */}
                <DropdownMenuGroup>
                  <DropdownMenuLabel className="font-normal">
                    <p className="truncate text-sm font-medium text-foreground">
                      {me.first_name} {me.last_name}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{me.email}</p>
                  </DropdownMenuLabel>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={logout} data-testid="logout">
                  <LogOutIcon />
                  {t("common.logout")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}
