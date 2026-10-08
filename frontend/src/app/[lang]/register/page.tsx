"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { MailCheckIcon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AuthCard, Field } from "@/components/auth-card";
import { useI18n } from "@/i18n/client";
import { api } from "@/lib/api/client";
import { errorMessage, fieldErrors } from "@/lib/errors";

export default function RegisterPage() {
  const { locale, t } = useI18n();
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    setError(null);
    try {
      await api("/auth/register", {
        method: "POST",
        noRefresh: true,
        body: {
          email: form.get("email"),
          password: form.get("password"),
          first_name: form.get("first_name"),
          last_name: form.get("last_name"),
          student_number: String(form.get("student_number") ?? "").trim() || null,
          locale,
        },
      });
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }

  const login = (
    <Link href={`/${locale}/login`} className="font-medium text-primary underline-offset-4 hover:underline">
      {t("auth.loginLink")}
    </Link>
  );

  if (done) {
    return (
      <AuthCard title={t("auth.registeredTitle")} footer={login}>
        <div className="flex flex-col items-center gap-3 text-center" role="status">
          <MailCheckIcon className="size-10 text-primary" aria-hidden />
          <p className="text-sm text-muted-foreground">{t("auth.registeredText")}</p>
        </div>
      </AuthCard>
    );
  }

  const fields = fieldErrors(error);
  return (
    <AuthCard
      title={t("auth.registerTitle")}
      description={t("auth.registerSubtitle")}
      footer={
        <>
          {t("auth.haveAccount")} {login}
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
        {error != null && (
          <Alert variant="destructive" role="alert">
            <AlertDescription>{errorMessage(t, error)}</AlertDescription>
          </Alert>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="first_name" label={t("auth.firstName")} error={fields.first_name}>
            <Input id="first_name" name="first_name" autoComplete="given-name" required maxLength={100} />
          </Field>
          <Field id="last_name" label={t("auth.lastName")} error={fields.last_name}>
            <Input id="last_name" name="last_name" autoComplete="family-name" required maxLength={100} />
          </Field>
        </div>
        <Field id="email" label={t("auth.email")} error={fields.email}>
          <Input id="email" name="email" type="email" autoComplete="email" required dir="ltr" />
        </Field>
        <Field
          id="student_number"
          label={t("auth.studentNumber")}
          hint={t("auth.studentNumberHint")}
          error={fields.student_number}
        >
          <Input id="student_number" name="student_number" maxLength={32} dir="ltr" />
        </Field>
        <Field id="password" label={t("auth.password")} hint={t("auth.passwordHint")} error={fields.password}>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            maxLength={128}
            dir="ltr"
          />
        </Field>
        <Button type="submit" disabled={pending} className="w-full">
          {t("auth.submitRegister")}
        </Button>
      </form>
    </AuthCard>
  );
}
