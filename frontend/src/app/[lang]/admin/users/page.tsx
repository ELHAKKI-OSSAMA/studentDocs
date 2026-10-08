"use client";

import { useDeferredValue, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { PlusIcon, SearchIcon, UsersIcon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Field } from "@/components/auth-card";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { Pager } from "@/components/pager";
import { useI18n } from "@/i18n/client";
import { useApiMutation, useApiQuery, useHasPermission, useMe } from "@/lib/api/hooks";
import { PERMS, type Page, type Role, type StaffUser } from "@/lib/api/types";
import { errorMessage, fieldErrors } from "@/lib/errors";

const LIMIT = 25;
const ROLES: Role[] = ["STUDENT", "ADMIN", "SUPER_ADMIN"];

function CreateStaffDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const { t } = useI18n();
  const [error, setError] = useState<unknown>(null);
  const create = useApiMutation<Record<string, unknown>>((body) => ({ path: "/admin/users", method: "POST", body }), [
    "/admin/",
  ]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      await create.mutateAsync(Object.fromEntries(form.entries()));
      toast.success(t("common.created"));
      onOpenChange(false);
    } catch (err) {
      setError(err);
    }
  }

  const errors = fieldErrors(error);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("users.createStaff")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" data-testid="staff-form">
          {error != null && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{errorMessage(t, error)}</AlertDescription>
            </Alert>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="s-first" label={t("auth.firstName")} error={errors.first_name}>
              <Input id="s-first" name="first_name" required maxLength={100} />
            </Field>
            <Field id="s-last" label={t("auth.lastName")} error={errors.last_name}>
              <Input id="s-last" name="last_name" required maxLength={100} />
            </Field>
          </div>
          <Field id="s-email" label={t("auth.email")} error={errors.email}>
            <Input id="s-email" name="email" type="email" required dir="ltr" />
          </Field>
          <Field id="s-role" label={t("users.role")}>
            <NativeSelect id="s-role" name="role" defaultValue="ADMIN">
              <option value="ADMIN">{t("users.ADMIN")}</option>
              <option value="SUPER_ADMIN">{t("users.SUPER_ADMIN")}</option>
            </NativeSelect>
          </Field>
          <Field id="s-pass" label={t("users.initialPassword")} hint={t("users.initialPasswordHint")} error={errors.password}>
            <Input id="s-pass" name="password" type="password" autoComplete="new-password" required minLength={12} dir="ltr" />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {t("common.create")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function UsersPage() {
  const { locale, t } = useI18n();
  const { data: me } = useMe();
  const canManage = useHasPermission(PERMS.usersManage);
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const query = useDeferredValue(q.trim());
  const list = useApiQuery<Page<StaffUser>>("/admin/users", { q: query, role, limit: LIMIT, offset });
  const update = useApiMutation<{ id: string; body: Record<string, unknown> }>(
    ({ id, body }) => ({ path: `/admin/users/${id}`, method: "PATCH", body }),
    ["/admin/"],
  );
  const date = new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" });

  async function patch(id: string, body: Record<string, unknown>) {
    try {
      await update.mutateAsync({ id, body });
      toast.success(t("common.saved"));
    } catch (err) {
      toast.error(errorMessage(t, err));
    }
  }

  return (
    <>
      <PageHeader
        title={t("users.title")}
        actions={
          canManage && (
            <Button onClick={() => setCreating(true)} data-testid="create-staff">
              <PlusIcon />
              {t("users.createStaff")}
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="relative w-full max-w-sm">
          <SearchIcon className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            type="search"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
            placeholder={t("users.searchPlaceholder")}
            aria-label={t("common.search")}
            className="ps-8"
          />
        </div>
        <div className="w-48">
          <NativeSelect aria-label={t("users.role")} value={role} onChange={(e) => { setRole(e.target.value); setOffset(0); }}>
            <option value="">{t("common.all")}</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`users.${r}`)}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>
      <Card>
        <CardContent>
          <QueryState isPending={list.isPending} error={list.error} onRetry={() => list.refetch()}>
            {list.data?.items.length ? (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("common.name")}</TableHead>
                      <TableHead>{t("auth.email")}</TableHead>
                      <TableHead>{t("users.role")}</TableHead>
                      <TableHead>{t("common.status")}</TableHead>
                      <TableHead>{t("users.lastLogin")}</TableHead>
                      {canManage && <TableHead className="text-end">{t("common.actions")}</TableHead>}
                    </TableRow>
                  </TableHeader>
                  <TableBody data-testid="users-rows">
                    {list.data.items.map((u) => {
                      const self = u.id === me?.id;
                      const staff = u.role !== "STUDENT";
                      return (
                        <TableRow key={u.id}>
                          <TableCell className="font-medium">
                            {u.first_name} {u.last_name}
                          </TableCell>
                          <TableCell dir="ltr" className="text-start">{u.email}</TableCell>
                          <TableCell>
                            {canManage && staff && !self ? (
                              <NativeSelect
                                aria-label={t("users.role")}
                                className="h-8 w-48"
                                value={u.role}
                                onChange={(e) => patch(u.id, { role: e.target.value })}
                              >
                                <option value="ADMIN">{t("users.ADMIN")}</option>
                                <option value="SUPER_ADMIN">{t("users.SUPER_ADMIN")}</option>
                              </NativeSelect>
                            ) : (
                              t(`users.${u.role}`)
                            )}
                          </TableCell>
                          <TableCell>
                            <Badge variant={u.is_active ? "secondary" : "destructive"}>
                              {t(u.is_active ? "common.active" : "common.inactive")}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {u.last_login_at ? date.format(new Date(u.last_login_at)) : t("users.never")}
                          </TableCell>
                          {canManage && (
                            <TableCell className="text-end">
                              {!self && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => patch(u.id, { is_active: !u.is_active })}
                                  data-testid={`toggle-${u.email}`}
                                >
                                  {t(u.is_active ? "users.deactivate" : "users.activate")}
                                </Button>
                              )}
                            </TableCell>
                          )}
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
                <Pager total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
              </>
            ) : (
              <EmptyState icon={UsersIcon} text={t("common.noData")} />
            )}
          </QueryState>
        </CardContent>
      </Card>
      {creating && <CreateStaffDialog open={creating} onOpenChange={setCreating} />}
    </>
  );
}
