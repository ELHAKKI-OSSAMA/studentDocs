"use client";

import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Field } from "@/components/auth-card";
import { QueryState } from "@/components/page";
import { useI18n } from "@/i18n/client";
import type { TranslationKey } from "@/i18n/translate";
import { api } from "@/lib/api/client";
import { useApiQuery, useInvalidate, useMe } from "@/lib/api/hooks";
import type {
  SmtpSecurity,
  SmtpSettings,
  SmtpTestResult,
} from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/requests";

const PATH = "/admin/settings/smtp";
const DEFAULT_PORT: Record<SmtpSecurity, number> = {
  SSL: 465,
  STARTTLS: 587,
  NONE: 25,
};

type Form = {
  is_enabled: boolean;
  host: string;
  port: number;
  security: SmtpSecurity;
  username: string;
  password: string;
  clear_password: boolean;
  mail_from: string;
};

function initial(data: SmtpSettings): Form {
  return {
    is_enabled: data.is_enabled ?? false,
    host: data.host ?? "",
    port: data.port ?? 465,
    security: data.security ?? "SSL",
    username: data.username ?? "",
    password: "",
    clear_password: false,
    mail_from: data.mail_from ?? "",
  };
}

/** Super-admin only (settings.manage): the password is write-only, never sent back by the API. */
export function SmtpSettingsCard() {
  const { t } = useI18n();
  const settings = useApiQuery<SmtpSettings>(PATH);
  const data = settings.data;
  return (
    <Card data-testid="smtp-settings">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {t("smtp.title")}
          {data && (
            <Badge
              variant={
                data.active_source === "database" ? "default" : "secondary"
              }
              data-testid="smtp-active-source"
            >
              {t(
                data.active_source === "database"
                  ? "smtp.activeDatabase"
                  : "smtp.activeEnvironment",
              )}
            </Badge>
          )}
        </CardTitle>
        <CardDescription>
          {t("smtp.description", {
            host: data
              ? `${data.environment_host}:${data.environment_port}`
              : "…",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <QueryState
          isPending={settings.isPending}
          error={settings.error}
          onRetry={() => settings.refetch()}
        >
          {/* Remounted after each save so the form restarts from the stored values. */}
          {data && !data.database_settings_allowed && (
            <Alert className="mb-4" data-testid="smtp-database-disabled">
              <AlertDescription>{t("smtp.databaseDisabled")}</AlertDescription>
            </Alert>
          )}
          {data && <SmtpForm key={data.updated_at ?? "new"} data={data} />}
        </QueryState>
      </CardContent>
    </Card>
  );
}

function SmtpForm({ data }: { data: SmtpSettings }) {
  const { locale, t } = useI18n();
  const me = useMe();
  const refresh = useInvalidate();
  const [form, setForm] = useState<Form>(() => initial(data));
  const [typedTo, setTypedTo] = useState<string | null>(null);
  const testTo = typedTo ?? me.data?.email ?? "";
  const setTestTo = setTypedTo;
  const [busy, setBusy] = useState<"save" | "test" | null>(null);
  const [result, setResult] = useState<SmtpTestResult | null>(null);

  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  function body() {
    return {
      ...form,
      username: form.username.trim() || null,
      password: form.password || null,
      port: Number(form.port),
    };
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy("save");
    try {
      await api(PATH, { method: "PUT", body: body() });
      toast.success(t("smtp.saved"));
      await refresh([PATH]);
    } catch (err) {
      toast.error(errorMessage(t, err));
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setResult(null);
    try {
      setResult(
        await api<SmtpTestResult>(`${PATH}/test`, {
          method: "POST",
          body: { ...body(), to: testTo },
        }),
      );
    } catch (err) {
      toast.error(errorMessage(t, err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <form onSubmit={save} className="grid gap-4" data-testid="smtp-form">
      {data && !data.password_readable && (
        <Alert variant="destructive">
          <AlertDescription>{t("smtp.passwordUnreadable")}</AlertDescription>
        </Alert>
      )}
      <label className="flex cursor-pointer items-center gap-3 text-sm font-medium">
        <Checkbox
          checked={form.is_enabled}
          onCheckedChange={(on) => set("is_enabled", !!on)}
          data-testid="smtp-enabled"
        />
        {t("smtp.enabled")}
      </label>
      <div className="grid gap-4 sm:grid-cols-[1fr_7rem_10rem]">
        <Field id="smtp-host" label={t("smtp.host")}>
          <Input
            id="smtp-host"
            dir="ltr"
            required
            maxLength={253}
            placeholder="smtp.gmail.com"
            value={form.host}
            onChange={(e) => set("host", e.target.value)}
          />
        </Field>
        <Field id="smtp-port" label={t("smtp.port")}>
          <Input
            id="smtp-port"
            type="number"
            dir="ltr"
            required
            min={1}
            max={65535}
            value={form.port}
            onChange={(e) => set("port", Number(e.target.value))}
          />
        </Field>
        <Field id="smtp-security" label={t("smtp.security")}>
          <NativeSelect
            id="smtp-security"
            value={form.security}
            onChange={(e) => {
              const security = e.target.value as SmtpSecurity;
              setForm((f) => ({
                ...f,
                security,
                port: DEFAULT_PORT[security],
              }));
            }}
          >
            <option value="SSL">SSL / TLS</option>
            <option value="STARTTLS">STARTTLS</option>
            <option value="NONE">{t("smtp.securityNone")}</option>
          </NativeSelect>
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          id="smtp-username"
          label={`${t("smtp.username")} (${t("requests.optional")})`}
        >
          <Input
            id="smtp-username"
            dir="ltr"
            autoComplete="off"
            maxLength={255}
            value={form.username}
            onChange={(e) => set("username", e.target.value)}
          />
        </Field>
        <Field
          id="smtp-password"
          label={t("smtp.password")}
          hint={data.has_password ? t("smtp.passwordKeep") : undefined}
        >
          <Input
            id="smtp-password"
            type="password"
            dir="ltr"
            autoComplete="new-password"
            maxLength={512}
            placeholder={data.has_password ? "••••••••" : ""}
            value={form.password}
            disabled={form.clear_password}
            onChange={(e) => set("password", e.target.value)}
          />
        </Field>
      </div>
      {data.has_password && (
        <label className="flex cursor-pointer items-center gap-3 text-sm">
          <Checkbox
            checked={form.clear_password}
            onCheckedChange={(on) => set("clear_password", !!on)}
          />
          {t("smtp.clearPassword")}
        </label>
      )}
      <Field
        id="smtp-from"
        label={t("smtp.mailFrom")}
        hint={t("smtp.mailFromHint")}
      >
        <Input
          id="smtp-from"
          dir="ltr"
          required
          maxLength={320}
          placeholder="StudentDocs <scolarite@universite.ma>"
          value={form.mail_from}
          onChange={(e) => set("mail_from", e.target.value)}
        />
      </Field>

      <div className="flex flex-wrap items-end gap-3 border-t pt-4">
        <Field id="smtp-test-to" label={t("smtp.testTo")}>
          <Input
            id="smtp-test-to"
            type="email"
            dir="ltr"
            className="min-w-64"
            value={testTo}
            onChange={(e) => setTestTo(e.target.value)}
          />
        </Field>
        <Button
          type="button"
          variant="outline"
          disabled={busy !== null || !form.host || !testTo}
          onClick={test}
          data-testid="smtp-test"
        >
          {busy === "test" ? t("smtp.testing") : t("smtp.test")}
        </Button>
        <Button
          type="submit"
          disabled={busy !== null}
          data-testid="smtp-save"
          className="ms-auto"
        >
          {t("common.save")}
        </Button>
      </div>
      {result && (
        <Alert
          variant={result.ok ? "default" : "destructive"}
          data-testid="smtp-test-result"
          data-ok={result.ok}
        >
          <AlertDescription>
            {result.ok
              ? t("smtp.testOk", { to: testTo })
              : t(`errors.${result.error}` as TranslationKey)}
          </AlertDescription>
        </Alert>
      )}
      {data.updated_at && (
        <p className="text-xs text-muted-foreground">
          {t("smtp.updated", {
            date: formatDateTime(data.updated_at, locale),
            name: data.updated_by_name ?? "—",
          })}
        </p>
      )}
    </form>
  );
}
