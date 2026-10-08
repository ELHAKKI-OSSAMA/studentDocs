"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthCard, Field } from "@/components/auth-card";
import { useI18n } from "@/i18n/client";
import { api, ApiError } from "@/lib/api/client";
import { meKey } from "@/lib/api/hooks";
import type { Me } from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { safeNext } from "@/lib/routing";

function LoginForm() {
  const { locale, t } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const [email, setEmail] = useState("");
  const [resent, setResent] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/login", {
        method: "POST",
        body: { email: form.get("email"), password: form.get("password") },
        noRefresh: true,
      });
      qc.setQueryData(meKey, me);
      const home = `/${locale}/${me.permissions.includes("admin.access") ? "admin" : "student"}`;
      router.replace(safeNext(params.get("next"), locale, home));
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  async function resend() {
    await api("/auth/resend-verification", { method: "POST", body: { email }, noRefresh: true }).catch(
      () => undefined,
    );
    setResent(true);
  }

  const notVerified = error instanceof ApiError && error.code === "email_not_verified";

  return (
    <AuthCard
      title={t("auth.loginTitle")}
      description={t("auth.loginSubtitle")}
      footer={
        <>
          {t("auth.noAccount")}{" "}
          <Link href={`/${locale}/register`} className="font-medium text-primary underline-offset-4 hover:underline">
            {t("auth.registerLink")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        {error != null && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{errorMessage(t, error)}</AlertDescription>
          </Alert>
        )}
        {notVerified && (
          <Button type="button" variant="outline" onClick={resend} disabled={resent}>
            {resent ? t("auth.resendSent") : t("auth.resend")}
          </Button>
        )}
        <Field id="email" label={t("auth.email")}>
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="username"
            required
            dir="ltr"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field id="password" label={t("auth.password")}>
          <Input id="password" name="password" type="password" autoComplete="current-password" required dir="ltr" />
        </Field>
        <Button type="submit" disabled={pending} className="w-full">
          {t("auth.submitLogin")}
        </Button>
      </form>
    </AuthCard>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
