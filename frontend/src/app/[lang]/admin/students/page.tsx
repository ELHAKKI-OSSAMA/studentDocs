"use client";

import { useDeferredValue, useState } from "react";
import { SearchIcon, UsersIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { Pager } from "@/components/pager";
import { useI18n } from "@/i18n/client";
import { useApiQuery } from "@/lib/api/hooks";
import type { Page, StudentListItem } from "@/lib/api/types";

const LIMIT = 25;

export default function StudentsPage() {
  const { locale, t } = useI18n();
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const query = useDeferredValue(q.trim());
  const list = useApiQuery<Page<StudentListItem>>("/admin/students", { q: query, limit: LIMIT, offset });
  const date = new Intl.DateTimeFormat(locale, { dateStyle: "medium" });

  return (
    <>
      <PageHeader title={t("students.title")} />
      <div className="relative mb-4 max-w-sm">
        <SearchIcon className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
        <Input
          type="search"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOffset(0);
          }}
          placeholder={t("students.searchPlaceholder")}
          aria-label={t("common.search")}
          className="ps-8"
          maxLength={100}
        />
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
                      <TableHead>{t("student.studentNumber")}</TableHead>
                      <TableHead>{t("common.status")}</TableHead>
                      <TableHead>{t("students.registeredAt")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {list.data.items.map((s) => (
                      <TableRow key={s.id}>
                        <TableCell className="font-medium">
                          {s.first_name} {s.last_name}
                        </TableCell>
                        <TableCell dir="ltr" className="text-start">{s.email}</TableCell>
                        <TableCell>{s.student_number ?? "—"}</TableCell>
                        <TableCell className="space-x-1 rtl:space-x-reverse">
                          <Badge variant={s.email_verified ? "secondary" : "outline"}>
                            {t(s.email_verified ? "users.verified" : "users.pending")}
                          </Badge>
                          {!s.is_active && <Badge variant="destructive">{t("common.inactive")}</Badge>}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{date.format(new Date(s.created_at))}</TableCell>
                      </TableRow>
                    ))}
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
    </>
  );
}
