import Link from "next/link";
import { notFound } from "next/navigation";
import { GraduationCapIcon } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { LanguageSwitcher } from "@/components/language-switcher";
import { isLocale } from "@/i18n/config";
import { getDictionary } from "@/i18n/dictionaries";
import { SystemStatus } from "./system-status";

export default async function Home({ params }: PageProps<"/[lang]">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const dict = await getDictionary(lang);

  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex items-center justify-between px-4 py-3 md:px-8">
        <span className="flex items-center gap-2 font-semibold text-primary">
          <GraduationCapIcon className="size-5" aria-hidden />
          {dict.app.name}
        </span>
        <LanguageSwitcher />
      </header>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-10 px-4 py-16">
        <section className="flex flex-col gap-4">
          <h1 className="text-3xl font-bold tracking-tight md:text-4xl">{dict.home.title}</h1>
          <p className="text-lg text-muted-foreground">{dict.home.subtitle}</p>
          <div className="flex flex-wrap gap-3 pt-2">
            <Link href={`/${lang}/login`} className={buttonVariants({ size: "lg" })}>
              {dict.home.login}
            </Link>
            <Link href={`/${lang}/register`} className={buttonVariants({ size: "lg", variant: "outline" })}>
              {dict.home.register}
            </Link>
          </div>
        </section>
        <SystemStatus labels={{ title: dict.home.status, ok: dict.home.statusOk, down: dict.home.statusDown }} />
      </main>
    </div>
  );
}
