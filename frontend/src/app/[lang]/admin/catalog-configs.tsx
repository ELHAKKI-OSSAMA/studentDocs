"use client";

import { Badge } from "@/components/ui/badge";
import { ActiveBadge, CatalogCrud, type CatalogConfig } from "@/components/catalog-crud";
import { useI18n } from "@/i18n/client";
import { localized, type I18nText } from "@/i18n/translate";
import type { AcademicYear, Branch, BranchCategory, DocumentType, StudyLevel } from "@/lib/api/types";

const CODE = "[A-Za-z0-9][A-Za-z0-9_]{0,47}";

function Name({ text }: { text: I18nText }) {
  const { locale } = useI18n();
  return <span className="font-medium">{localized(text, locale)}</span>;
}

function Mono({ children }: { children: string }) {
  return <code className="rounded bg-muted px-1.5 py-0.5 text-xs" dir="ltr">{children}</code>;
}

export function AcademicYearsPage() {
  const { t } = useI18n();
  const config: CatalogConfig<AcademicYear> = {
    title: "nav.academicYears",
    path: "/academic-years",
    fields: [
      { name: "label", label: "catalog.label", kind: "text", required: true, pattern: "\\d{4}-\\d{4}", hint: "catalog.labelHint", createOnly: true, ltr: true },
      { name: "start_date", label: "catalog.startDate", kind: "date" },
      { name: "end_date", label: "catalog.endDate", kind: "date" },
      { name: "status", label: "common.status", kind: "select", options: [
        { value: "ACTIVE", label: "catalog.ACTIVE" },
        { value: "ARCHIVED", label: "catalog.ARCHIVED" },
      ] },
    ],
    columns: [
      { header: "catalog.label", cell: (y) => <span className="font-medium">{y.label}</span> },
      { header: "catalog.startDate", cell: (y) => y.start_date },
      { header: "catalog.endDate", cell: (y) => y.end_date },
      { header: "common.status", cell: (y) => (
        <Badge variant={y.status === "ACTIVE" ? "secondary" : "outline"}>{t(`catalog.${y.status}`)}</Badge>
      ) },
    ],
  };
  return <CatalogCrud config={config} />;
}

export function BranchCategoriesPage() {
  const config: CatalogConfig<BranchCategory> = {
    title: "nav.branchCategories",
    path: "/branch-categories",
    fields: [
      { name: "code", label: "common.code", kind: "text", required: true, pattern: CODE, hint: "catalog.codeHint", createOnly: true, ltr: true },
      { name: "name_i18n", label: "common.name", kind: "i18n" },
      { name: "sort_order", label: "catalog.sortOrder", kind: "number", min: 0, max: 1000 },
      { name: "is_active", label: "catalog.isActive", kind: "checkbox" },
    ],
    columns: [
      { header: "common.code", cell: (c) => <Mono>{c.code}</Mono> },
      { header: "common.name", cell: (c) => <Name text={c.name_i18n} /> },
      { header: "catalog.sortOrder", cell: (c) => c.sort_order },
      { header: "common.status", cell: (c) => <ActiveBadge active={c.is_active} /> },
    ],
  };
  return <CatalogCrud config={config} />;
}

export function BranchesPage() {
  const config: CatalogConfig<Branch> = {
    title: "nav.branches",
    path: "/branches",
    filterByCategory: true,
    fields: [
      { name: "category_id", label: "catalog.category", kind: "category", createOnly: true, hint: "catalog.categoryFixed" },
      { name: "code", label: "common.code", kind: "text", required: true, pattern: CODE, hint: "catalog.codeHint", createOnly: true, ltr: true },
      { name: "name_i18n", label: "common.name", kind: "i18n" },
      { name: "is_active", label: "catalog.isActive", kind: "checkbox" },
    ],
    columns: [
      { header: "common.code", cell: (b) => <Mono>{b.code}</Mono> },
      { header: "common.name", cell: (b) => <Name text={b.name_i18n} /> },
      { header: "catalog.category", cell: (b) => <Name text={b.category.name_i18n} /> },
      { header: "common.status", cell: (b) => <ActiveBadge active={b.is_active} /> },
    ],
  };
  return <CatalogCrud config={config} />;
}

export function StudyLevelsPage() {
  const config: CatalogConfig<StudyLevel> = {
    title: "nav.studyLevels",
    path: "/study-levels",
    filterByCategory: true,
    fields: [
      { name: "category_id", label: "catalog.category", kind: "category", createOnly: true, hint: "catalog.categoryFixed" },
      { name: "code", label: "common.code", kind: "text", required: true, pattern: "[A-Za-z0-9][A-Za-z0-9_]{0,15}", hint: "catalog.codeHint", createOnly: true, ltr: true },
      { name: "name_i18n", label: "common.name", kind: "i18n" },
      { name: "sort_order", label: "catalog.sortOrder", kind: "number", min: 0, max: 100 },
      { name: "is_active", label: "catalog.isActive", kind: "checkbox" },
    ],
    columns: [
      { header: "common.code", cell: (l) => <Mono>{l.code}</Mono> },
      { header: "common.name", cell: (l) => <Name text={l.name_i18n} /> },
      { header: "catalog.category", cell: (l) => <Name text={l.category.name_i18n} /> },
      { header: "common.status", cell: (l) => <ActiveBadge active={l.is_active} /> },
    ],
  };
  return <CatalogCrud config={config} />;
}

function DocumentTypeCategories({ doc }: { doc: DocumentType }) {
  const { locale, t } = useI18n();
  if (!doc.allowed_categories.length) return <span className="text-muted-foreground">{t("catalog.allCategories")}</span>;
  return <>{doc.allowed_categories.map((c) => localized(c.name_i18n, locale)).join(", ")}</>;
}

export function DocumentTypesPage() {
  const { t } = useI18n();
  const config: CatalogConfig<DocumentType> = {
    title: "nav.documentTypes",
    path: "/document-types",
    filterByCategory: true,
    fields: [
      { name: "code", label: "common.code", kind: "text", required: true, pattern: CODE, hint: "catalog.codeHint", createOnly: true, ltr: true },
      { name: "name_i18n", label: "common.name", kind: "i18n" },
      { name: "delivery_mode", label: "catalog.deliveryMode", kind: "select", options: [
        { value: "DIGITAL", label: "catalog.DIGITAL" },
        { value: "PICKUP", label: "catalog.PICKUP" },
      ] },
      { name: "max_quantity", label: "catalog.maxQuantity", kind: "number", min: 1, max: 10 },
      { name: "processing_days", label: "catalog.processingDays", kind: "number", min: 0, max: 90 },
      { name: "requires_attachment", label: "catalog.requiresAttachment", kind: "checkbox" },
      { name: "requires_deposit", label: "catalog.requiresDeposit", kind: "checkbox", hint: "catalog.requiresDepositHint" },
      { name: "allowed_category_ids", label: "catalog.allowedCategories", kind: "categories", hint: "catalog.allowedCategoriesHint" },
      { name: "is_active", label: "catalog.isActive", kind: "checkbox" },
    ],
    columns: [
      { header: "common.code", cell: (d) => <Mono>{d.code}</Mono> },
      { header: "common.name", cell: (d) => <Name text={d.name_i18n} /> },
      { header: "catalog.deliveryMode", cell: (d) => t(`catalog.${d.delivery_mode}`) },
      { header: "catalog.processingDays", cell: (d) => d.processing_days, className: "tabular-nums" },
      { header: "catalog.allowedCategories", cell: (d) => <DocumentTypeCategories doc={d} /> },
      { header: "common.status", cell: (d) => <ActiveBadge active={d.is_active} /> },
    ],
  };
  return <CatalogCrud config={config} />;
}
