import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Noto_Sans, Noto_Sans_Arabic } from "next/font/google";
import { Providers } from "@/components/providers";
import { direction, isLocale, locales } from "@/i18n/config";
import { getDictionary } from "@/i18n/dictionaries";
import "../globals.css";

const latin = Noto_Sans({ variable: "--font-latin", subsets: ["latin"] });
const arabic = Noto_Sans_Arabic({ variable: "--font-arabic", subsets: ["arabic"] });

export function generateStaticParams() {
  return locales.map((lang) => ({ lang }));
}

export async function generateMetadata({ params }: LayoutProps<"/[lang]">): Promise<Metadata> {
  const { lang } = await params;
  if (!isLocale(lang)) return {};
  const dict = await getDictionary(lang);
  return { title: { default: dict.app.name, template: `%s · ${dict.app.name}` }, description: dict.app.tagline };
}

export default async function LocaleLayout({ children, params }: LayoutProps<"/[lang]">) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const dictionary = await getDictionary(lang);

  return (
    <html
      lang={lang}
      dir={direction(lang)}
      className={`${latin.variable} ${arabic.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <Providers locale={lang} dictionary={dictionary}>
          {children}
        </Providers>
      </body>
    </html>
  );
}
