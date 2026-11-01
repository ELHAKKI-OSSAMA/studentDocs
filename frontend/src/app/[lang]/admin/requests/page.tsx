"use client";

import Link from "next/link";
import { useState } from "react";
import { InboxIcon, SearchIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { Pager } from "@/components/pager";
import { StatusBadge } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { localized } from "@/i18n/translate";
import { useApiQuery } from "@/lib/api/hooks";
import {
  REQUEST_STATUSES,
  type AcademicYear,
  type Branch,
  type BranchCategory,
  type Page,
  type RequestListItem,
} from "@/lib/api/types";
import { formatDate } from "@/lib/requests";

const LIMIT = 25;

export default function AdminRequestsPage() {
  const { locale, t } = useI18n();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState({
    status: "",
    academic_year_id: "",
    category_id: "",
    branch_id: "",
    assigned: "",
  });
  const [offset, setOffset] = useState(0);
  const years = useApiQuery<AcademicYear[]>("/catalog/academic-years");
  const categories = useApiQuery<BranchCategory[]>("/catalog/branch-categories");
  const branches = useApiQuery<Branch[]>("/catalog/branches", { category_id: filters.category_id || undefined });
  const requests = useApiQuery<Page<RequestListItem>>("/admin/requests", { ...filters, q, limit: LIMIT, offset });

  function setFilter(name: keyof typeof filters, value: string) {
    setFilters((f) => ({ ...f, [name]: value, ...(name === "category_id" ? { branch_id: "" } : {}) }));
    setOffset(0);
  }

  return (
    <>
      <PageHeader title={t("nav.requests")} />
      <Card>
        <CardContent className="space-y-4">
          <form
            className="relative"
            onSubmit={(e) => {
              e.preventDefault();
              setQ(search.trim());
              setOffset(0);
            }}
          >
            <SearchIcon className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("requests.searchPlaceholder")}
              aria-label={t("common.search")}
              className="ps-8"
              maxLength={100}
              data-testid="request-search"
            />
          </form>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <NativeSelect
              aria-label={t("common.status")}
              value={filters.status}
              onChange={(e) => setFilter("status", e.target.value)}
              data-testid="filter-status"
            >
              <option value="">{t("requests.allStatuses")}</option>
              {REQUEST_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`status.${s}`)}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label={t("requests.year")}
              value={filters.academic_year_id}
              onChange={(e) => setFilter("academic_year_id", e.target.value)}
            >
              <option value="">{t("requests.allYears")}</option>
              {years.data?.map((y) => (
                <option key={y.id} value={y.id}>
                  {y.label}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label={t("requests.category")}
              value={filters.category_id}
              onChange={(e) => setFilter("category_id", e.target.value)}
            >
              <option value="">{t("requests.allCategories")}</option>
              {categories.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {localized(c.name_i18n, locale)}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label={t("requests.branch")}
              value={filters.branch_id}
              onChange={(e) => setFilter("branch_id", e.target.value)}
            >
              <option value="">{t("requests.allBranches")}</option>
              {branches.data?.map((b) => (
                <option key={b.id} value={b.id}>
                  {localized(b.name_i18n, locale)}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label={t("requests.assignedTo")}
              value={filters.assigned}
              onChange={(e) => setFilter("assigned", e.target.value)}
              data-testid="filter-assigned"
            >
              <option value="">{t("requests.assignedAll")}</option>
              <option value="me">{t("requests.assignedMe")}</option>
              <option value="unassigned">{t("requests.assignedNone")}</option>
            </NativeSelect>
          </div>

          <QueryState isPending={requests.isPending} error={requests.error} onRetry={() => requests.refetch()}>
            {requests.data?.items.length ? (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("requests.reference")}</TableHead>
                      <TableHead>{t("requests.studentInfo")}</TableHead>
                      <TableHead>{t("requests.documents")}</TableHead>
                      <TableHead>{t("requests.branch")}</TableHead>
                      <TableHead>{t("common.status")}</TableHead>
                      <TableHead>{t("requests.assignedTo")}</TableHead>
                      <TableHead>{t("requests.date")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody data-testid="admin-requests-table">
                    {requests.data.items.map((r) => (
                      <TableRow key={r.id} data-reference={r.reference}>
                        <TableCell>
                          <Link
                            href={`/${locale}/admin/requests/${r.id}`}
                            className="font-mono font-medium text-primary hover:underline"
                            dir="ltr"
                          >
                            {r.reference}
                          </Link>
                          {r.unread_messages > 0 && (
                            <Badge className="ms-2">{t("requests.unread", { n: r.unread_messages })}</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          {r.student && (
                            <Link href={`/${locale}/admin/students/${r.student.id}`} className="font-medium hover:underline">
                              {r.student.first_name} {r.student.last_name}
                            </Link>
                          )}
                          <p className="text-xs text-muted-foreground" dir="ltr">
                            {r.student?.student_number ?? r.student?.email}
                          </p>
                        </TableCell>
                        <TableCell className="max-w-56 truncate">
                          {r.items.map((i) => localized(i.document_type.name_i18n, locale)).join(", ")}
                        </TableCell>
                        <TableCell>
                          {localized(r.branch.name_i18n, locale)}
                          <p className="text-xs text-muted-foreground">{r.academic_year.label}</p>
                        </TableCell>
                        <TableCell>
                          <StatusBadge status={r.status} />
                        </TableCell>
                        <TableCell className="text-sm">
                          {r.assigned_to ? (
                            `${r.assigned_to.first_name} ${r.assigned_to.last_name}`
                          ) : (
                            <span className="text-muted-foreground">{t("requests.unassigned")}</span>
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{formatDate(r.created_at, locale)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pager total={requests.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
              </>
            ) : (
              <EmptyState icon={InboxIcon} text={t("requests.empty")} />
            )}
          </QueryState>
        </CardContent>
      </Card>
    </>
  );
}
