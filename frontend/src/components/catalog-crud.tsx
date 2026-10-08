"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";
import { InboxIcon, PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Field } from "@/components/auth-card";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { useI18n } from "@/i18n/client";
import { localized, type I18nText, type TranslationKey } from "@/i18n/translate";
import { useApiMutation, useApiQuery, useHasPermission } from "@/lib/api/hooks";
import { PERMS, type BranchCategory } from "@/lib/api/types";
import { errorMessage, fieldErrors } from "@/lib/errors";

type Base = { name: string; label: TranslationKey; hint?: TranslationKey; createOnly?: boolean };

export type FieldDef = Base &
  (
    | { kind: "text"; required?: boolean; pattern?: string; maxLength?: number; ltr?: boolean }
    | { kind: "date" }
    | { kind: "number"; min: number; max: number }
    | { kind: "checkbox" }
    | { kind: "select"; options: { value: string; label: TranslationKey }[] }
    | { kind: "i18n" }
    | { kind: "category" }
    | { kind: "categories" }
  );

export type Column<T> = { header: TranslationKey; cell: (item: T) => ReactNode; className?: string };

type Item = { id: string } & Record<string, unknown>;

export type CatalogConfig<T extends Item> = {
  title: TranslationKey;
  /** Path below /admin/catalog, e.g. "/branches". */
  path: string;
  fields: FieldDef[];
  columns: Column<T>[];
  filterByCategory?: boolean;
};

function useCategories() {
  return useApiQuery<BranchCategory[]>("/admin/catalog/branch-categories");
}

/** Converts the dialog form into the API payload, field by field. */
function toBody(fields: FieldDef[], form: FormData, editing: boolean): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const f of fields) {
    if (editing && f.createOnly) continue;
    const raw = form.get(f.name);
    switch (f.kind) {
      case "text":
      case "date":
      case "select":
      case "category":
        body[f.name] = String(raw ?? "").trim();
        break;
      case "number":
        body[f.name] = Number(raw);
        break;
      case "checkbox":
        body[f.name] = form.get(f.name) === "on";
        break;
      case "categories":
        body[f.name] = form.getAll(f.name).map(String);
        break;
      case "i18n": {
        const v = (lang: string) => String(form.get(`${f.name}.${lang}`) ?? "").trim() || null;
        body[f.name] = { fr: v("fr") ?? "", en: v("en"), ar: v("ar") };
        break;
      }
    }
  }
  return body;
}

function FormField({
  field,
  item,
  error,
  categories,
}: {
  field: FieldDef;
  item: Item | null;
  error?: string;
  categories: BranchCategory[];
}) {
  const { locale, t } = useI18n();
  const id = `f-${field.name}`;
  const disabled = !!item && !!field.createOnly;
  const value = item?.[field.name];

  switch (field.kind) {
    case "i18n": {
      const text = (value as I18nText | undefined) ?? { fr: "" };
      return (
        <>
          {(["fr", "en", "ar"] as const).map((lang) => (
            <Field
              key={lang}
              id={`${id}-${lang}`}
              label={t(lang === "fr" ? "catalog.nameFr" : lang === "en" ? "catalog.nameEn" : "catalog.nameAr")}
              error={lang === "fr" ? error : undefined}
            >
              <Input
                id={`${id}-${lang}`}
                name={`${field.name}.${lang}`}
                defaultValue={text[lang] ?? ""}
                required={lang === "fr"}
                maxLength={200}
                dir={lang === "ar" ? "rtl" : "ltr"}
                lang={lang}
              />
            </Field>
          ))}
        </>
      );
    }
    case "checkbox":
      return (
        <label className="flex items-center gap-2 text-sm">
          <Checkbox name={field.name} defaultChecked={item ? Boolean(value) : true} />
          {t(field.label)}
        </label>
      );
    case "categories": {
      const selected = new Set(((value as { id: string }[] | undefined) ?? []).map((c) => c.id));
      return (
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium">{t(field.label)}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {categories.map((c) => (
              <label key={c.id} className="flex items-center gap-2 text-sm">
                <Checkbox name={field.name} value={c.id} defaultChecked={selected.has(c.id)} />
                {localized(c.name_i18n, locale)}
              </label>
            ))}
          </div>
          {field.hint && <p className="text-xs text-muted-foreground">{t(field.hint)}</p>}
        </fieldset>
      );
    }
    default:
      break;
  }

  let control: ReactNode;
  if (field.kind === "select" || field.kind === "category") {
    const current =
      field.kind === "category"
        ? ((value as { category?: { id: string } } | undefined)?.category?.id ??
          (item?.category as { id: string } | undefined)?.id ??
          "")
        : String(value ?? field.options[0]?.value ?? "");
    control = (
      <NativeSelect id={id} name={field.name} defaultValue={current} disabled={disabled} required>
        {field.kind === "category" ? (
          <>
            <option value="" disabled>
              {t("student.select")}
            </option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {localized(c.name_i18n, locale)}
              </option>
            ))}
          </>
        ) : (
          field.options.map((o) => (
            <option key={o.value} value={o.value}>
              {t(o.label)}
            </option>
          ))
        )}
      </NativeSelect>
    );
  } else {
    control = (
      <Input
        id={id}
        name={field.name}
        type={field.kind === "date" ? "date" : field.kind === "number" ? "number" : "text"}
        defaultValue={value == null ? (field.kind === "number" ? field.min : "") : String(value)}
        disabled={disabled}
        required={field.kind !== "text" || field.required}
        {...(field.kind === "number" ? { min: field.min, max: field.max } : {})}
        {...(field.kind === "text"
          ? { pattern: field.pattern, maxLength: field.maxLength, dir: field.ltr ? "ltr" : undefined }
          : {})}
      />
    );
  }
  return (
    <Field id={id} label={t(field.label)} hint={field.hint ? t(field.hint) : undefined} error={error}>
      {control}
    </Field>
  );
}

function EditDialog<T extends Item>({
  config,
  item,
  open,
  onOpenChange,
}: {
  config: CatalogConfig<T>;
  item: T | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const categories = useCategories();
  const base = `/admin/catalog${config.path}`;
  const save = useApiMutation<Record<string, unknown>>(
    (body) => (item ? { path: `${base}/${item.id}`, method: "PATCH", body } : { path: base, method: "POST", body }),
    ["/admin/", "/catalog/"],
  );
  const [error, setError] = useState<unknown>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await save.mutateAsync(toBody(config.fields, new FormData(event.currentTarget), !!item));
      toast.success(t(item ? "common.saved" : "common.created"));
      onOpenChange(false);
    } catch (err) {
      setError(err);
    }
  }

  const errors = fieldErrors(error);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t(item ? "catalog.editItem" : "catalog.newItem")}</DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-4" data-testid="catalog-form">
          {error != null && (
            <Alert variant="destructive" role="alert">
              <AlertDescription>{errorMessage(t, error)}</AlertDescription>
            </Alert>
          )}
          {config.fields.map((f) => (
            <FormField
              key={f.name}
              field={f}
              item={item}
              error={errors[f.name] ?? errors[`${f.name}.fr`]}
              categories={categories.data ?? []}
            />
          ))}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function CatalogCrud<T extends Item>({ config }: { config: CatalogConfig<T> }) {
  const { locale, t } = useI18n();
  const canManage = useHasPermission(PERMS.catalogManage);
  const [categoryId, setCategoryId] = useState("");
  const categories = useCategories();
  const base = `/admin/catalog${config.path}`;
  const list = useApiQuery<T[]>(base, config.filterByCategory ? { category_id: categoryId } : undefined);
  const remove = useApiMutation<string>((id) => ({ path: `${base}/${id}`, method: "DELETE" }), [
    "/admin/",
    "/catalog/",
  ]);
  const [editing, setEditing] = useState<{ open: boolean; item: T | null }>({ open: false, item: null });
  const [deleting, setDeleting] = useState<T | null>(null);

  async function confirmDelete() {
    if (!deleting) return;
    try {
      await remove.mutateAsync(deleting.id);
      toast.success(t("common.deleted"));
    } catch (err) {
      toast.error(errorMessage(t, err));
    } finally {
      setDeleting(null);
    }
  }

  return (
    <>
      <PageHeader
        title={t(config.title)}
        actions={
          canManage && (
            <Button onClick={() => setEditing({ open: true, item: null })} data-testid="catalog-create">
              <PlusIcon />
              {t("common.create")}
            </Button>
          )
        }
      />
      {!canManage && (
        <Alert className="mb-4">
          <AlertDescription>{t("admin.readOnly")}</AlertDescription>
        </Alert>
      )}
      {config.filterByCategory && (
        <div className="mb-4 max-w-xs">
          <NativeSelect
            aria-label={t("catalog.category")}
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
          >
            <option value="">{t("catalog.allCategories")}</option>
            {categories.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {localized(c.name_i18n, locale)}
              </option>
            ))}
          </NativeSelect>
        </div>
      )}
      <Card>
        <CardContent>
          <QueryState isPending={list.isPending} error={list.error} onRetry={() => list.refetch()}>
            {list.data?.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    {config.columns.map((c) => (
                      <TableHead key={c.header} className={c.className}>
                        {t(c.header)}
                      </TableHead>
                    ))}
                    {canManage && (
                      <TableHead className="w-24 text-end">
                        <span className="sr-only">{t("common.actions")}</span>
                      </TableHead>
                    )}
                  </TableRow>
                </TableHeader>
                <TableBody data-testid="catalog-rows">
                  {list.data.map((item) => (
                    <TableRow key={item.id}>
                      {config.columns.map((c) => (
                        <TableCell key={c.header} className={c.className}>
                          {c.cell(item)}
                        </TableCell>
                      ))}
                      {canManage && (
                        <TableCell className="text-end whitespace-nowrap">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={t("common.edit")}
                            onClick={() => setEditing({ open: true, item })}
                          >
                            <PencilIcon />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={t("common.delete")}
                            onClick={() => setDeleting(item)}
                          >
                            <Trash2Icon />
                          </Button>
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState icon={InboxIcon} text={t("common.noData")} />
            )}
          </QueryState>
        </CardContent>
      </Card>

      {editing.open && (
        <EditDialog
          config={config}
          item={editing.item}
          open={editing.open}
          onOpenChange={(open) => setEditing((s) => ({ ...s, open }))}
        />
      )}

      <AlertDialog open={!!deleting} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("common.confirmDeleteTitle")}</AlertDialogTitle>
            <AlertDialogDescription>{t("common.confirmDeleteText")}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("common.cancel")}</AlertDialogCancel>
            <Button variant="destructive" onClick={confirmDelete} disabled={remove.isPending} data-testid="confirm-delete">
              {t("common.delete")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

export function ActiveBadge({ active }: { active: boolean }) {
  const { t } = useI18n();
  return <Badge variant={active ? "secondary" : "outline"}>{t(active ? "common.active" : "common.inactive")}</Badge>;
}
