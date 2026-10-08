"use client";

import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { GraduationCapIcon, Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Field } from "@/components/auth-card";
import { EmptyState, PageHeader, QueryState } from "@/components/page";
import { EnrollmentBadge } from "@/components/requests";
import { useI18n } from "@/i18n/client";
import { localized } from "@/i18n/translate";
import { api } from "@/lib/api/client";
import { meKey, useApiMutation, useApiQuery, useMe } from "@/lib/api/hooks";
import type { AcademicYear, Branch, BranchCategory, Enrollment, Me, StudyLevel } from "@/lib/api/types";
import { errorMessage } from "@/lib/errors";

function PersonalInfo({ me }: { me: Me }) {
  const { t } = useI18n();
  const qc = useQueryClient();
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPending(true);
    try {
      const updated = await api<Me>("/auth/me", {
        method: "PATCH",
        body: { first_name: form.get("first_name"), last_name: form.get("last_name") },
      });
      qc.setQueryData(meKey, updated);
      toast.success(t("common.saved"));
    } catch (err) {
      toast.error(errorMessage(t, err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("student.personalInfo")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2">
          <Field id="first_name" label={t("auth.firstName")}>
            <Input id="first_name" name="first_name" defaultValue={me.first_name} required maxLength={100} />
          </Field>
          <Field id="last_name" label={t("auth.lastName")}>
            <Input id="last_name" name="last_name" defaultValue={me.last_name} required maxLength={100} />
          </Field>
          <Field id="email" label={t("auth.email")}>
            <Input id="email" value={me.email} disabled dir="ltr" />
          </Field>
          <Field id="student_number" label={t("student.studentNumber")}>
            <Input id="student_number" value={me.student?.student_number ?? t("student.notProvided")} disabled />
          </Field>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={pending}>
              {t("common.save")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function AddEnrollment() {
  const { locale, t } = useI18n();
  const [categoryId, setCategoryId] = useState("");
  const years = useApiQuery<AcademicYear[]>("/catalog/academic-years");
  const categories = useApiQuery<BranchCategory[]>("/catalog/branch-categories");
  const branches = useApiQuery<Branch[]>("/catalog/branches", { category_id: categoryId }, { enabled: !!categoryId });
  const levels = useApiQuery<StudyLevel[]>("/catalog/study-levels", { category_id: categoryId }, { enabled: !!categoryId });
  const add = useApiMutation<Record<string, FormDataEntryValue | null>>(
    (body) => ({ path: "/students/me/enrollments", method: "POST", body }),
    ["/students/me/enrollments"],
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    try {
      await add.mutateAsync({
        academic_year_id: form.get("academic_year_id"),
        branch_id: form.get("branch_id"),
        study_level_id: form.get("study_level_id"),
      });
      toast.success(t("student.enrollmentAdded"));
      formEl.reset();
      setCategoryId("");
    } catch (err) {
      toast.error(errorMessage(t, err));
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="enrollment-form">
      <Field id="academic_year_id" label={t("student.academicYear")}>
        <NativeSelect id="academic_year_id" name="academic_year_id" required defaultValue="">
          <option value="" disabled>
            {t("student.select")}
          </option>
          {years.data?.map((y) => (
            <option key={y.id} value={y.id}>
              {y.label}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="category" label={t("student.category")}>
        <NativeSelect id="category" required value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
          <option value="" disabled>
            {t("student.select")}
          </option>
          {categories.data?.map((c) => (
            <option key={c.id} value={c.id}>
              {localized(c.name_i18n, locale)}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="branch_id" label={t("student.branch")}>
        <NativeSelect id="branch_id" name="branch_id" required defaultValue="" key={`b-${categoryId}`} disabled={!categoryId}>
          <option value="" disabled>
            {t("student.select")}
          </option>
          {branches.data?.map((b) => (
            <option key={b.id} value={b.id}>
              {localized(b.name_i18n, locale)}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="study_level_id" label={t("student.level")}>
        <NativeSelect id="study_level_id" name="study_level_id" required defaultValue="" key={`l-${categoryId}`} disabled={!categoryId}>
          <option value="" disabled>
            {t("student.select")}
          </option>
          {levels.data?.map((l) => (
            <option key={l.id} value={l.id}>
              {localized(l.name_i18n, locale)}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <div className="sm:col-span-2 lg:col-span-4">
        <Button type="submit" disabled={add.isPending}>
          {t("student.addEnrollment")}
        </Button>
      </div>
    </form>
  );
}

function Enrollments() {
  const { locale, t } = useI18n();
  const enrollments = useApiQuery<Enrollment[]>("/students/me/enrollments");
  const remove = useApiMutation<string>(
    (id) => ({ path: `/students/me/enrollments/${id}`, method: "DELETE" }),
    ["/students/me/enrollments"],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("student.enrollmentsTitle")}</CardTitle>
        <CardDescription>{t("student.enrollmentsHint")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <QueryState isPending={enrollments.isPending} error={enrollments.error} onRetry={() => enrollments.refetch()}>
          {enrollments.data?.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("student.academicYear")}</TableHead>
                  <TableHead>{t("student.category")}</TableHead>
                  <TableHead>{t("student.branch")}</TableHead>
                  <TableHead>{t("student.level")}</TableHead>
                  <TableHead>{t("student.enrollmentStatus")}</TableHead>
                  <TableHead className="w-16">
                    <span className="sr-only">{t("common.actions")}</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody data-testid="enrollments-table">
                {enrollments.data.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell>{e.academic_year.label}</TableCell>
                    <TableCell>{localized(e.branch.category.name_i18n, locale)}</TableCell>
                    <TableCell>{localized(e.branch.name_i18n, locale)}</TableCell>
                    <TableCell>{localized(e.study_level.name_i18n, locale)}</TableCell>
                    <TableCell>
                      <EnrollmentBadge status={e.status} />
                      {e.review_note && (
                        <p className="mt-1 max-w-56 text-xs text-muted-foreground" data-testid="review-note">
                          {t("student.reviewNote", { note: e.review_note })}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>
                      {/* A verified enrollment can only be changed by the administration. */}
                      {e.status !== "VERIFIED" && (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={t("common.delete")}
                        onClick={() =>
                          remove.mutateAsync(e.id).then(
                            () => toast.success(t("student.enrollmentRemoved")),
                            (err) => toast.error(errorMessage(t, err)),
                          )
                        }
                      >
                        <Trash2Icon />
                      </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState icon={GraduationCapIcon} text={t("student.noEnrollments")} />
          )}
        </QueryState>
        <AddEnrollment />
      </CardContent>
    </Card>
  );
}

export default function ProfilePage() {
  const { t } = useI18n();
  const { data: me } = useMe();
  if (!me) return null;
  return (
    <>
      <PageHeader title={t("student.profileTitle")} />
      <div className="flex flex-col gap-6">
        <PersonalInfo me={me} />
        <Enrollments />
      </div>
    </>
  );
}
