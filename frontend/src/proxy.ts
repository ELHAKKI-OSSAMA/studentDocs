import { NextResponse, type NextRequest } from "next/server";
import { LOCALE_COOKIE } from "@/i18n/config";
import { resolveRedirect } from "@/lib/routing";

export function proxy(request: NextRequest) {
  const target = resolveRedirect({
    pathname: request.nextUrl.pathname,
    search: request.nextUrl.search,
    localeCookie: request.cookies.get(LOCALE_COOKIE)?.value,
    acceptLanguage: request.headers.get("accept-language"),
    sessionArea: request.cookies.get("sd_session")?.value,
  });
  if (!target) return;
  return NextResponse.redirect(new URL(target, request.url));
}

export const config = {
  matcher: ["/((?!api|_next|favicon.ico|.*\\..*).*)"],
};
