"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { CircleCheckIcon, CircleXIcon, LoaderIcon } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { AuthCard } from "@/components/auth-card";
import { useI18n } from "@/i18n/client";
import { api } from "@/lib/api/client";
import { errorMessage } from "@/lib/errors";

function Verify() {
  const { locale, t } = useI18n();
  const token = useSearchParams().get("token");
  const [result, setState] = useState<"pending" | "ok" | { error: unknown }>("pending");
  const started = useRef(false);
  const state = token ? result : { error: null };

  useEffect(() => {
    // Tokens are single-use: guard against React strict-mode double effects.
    if (!token || started.current) return;
    started.current = true;
    api("/auth/verify-email", { method: "POST", body: { token }, noRefresh: true })
      .then(() => setState("ok"))
      .catch((error) => setState({ error }));
  }, [token]);

  return (
    <AuthCard title={t("auth.verifyTitle")}>
      <div className="flex flex-col items-center gap-4 text-center" role="status">
        {state === "pending" && (
          <>
            <LoaderIcon className="size-8 animate-spin text-muted-foreground" aria-hidden />
            <p>{t("auth.verifying")}</p>
          </>
        )}
        {state === "ok" && (
          <>
            <CircleCheckIcon className="size-10 text-success" aria-hidden />
            <p data-testid="verify-success">{t("auth.verifiedText")}</p>
          </>
        )}
        {typeof state === "object" && (
          <>
            <CircleXIcon className="size-10 text-destructive" aria-hidden />
            <p>{token ? errorMessage(t, state.error) : t("errors.invalid_token")}</p>
          </>
        )}
        {state !== "pending" && (
          <Link href={`/${locale}/login`} className={buttonVariants()}>
            {t("auth.goToLogin")}
          </Link>
        )}
      </div>
    </AuthCard>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}
