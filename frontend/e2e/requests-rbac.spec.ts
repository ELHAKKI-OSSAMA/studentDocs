import { expect, test } from "@playwright/test";
import { accounts, byTestId, DEMO_PASSWORD } from "./helpers";
import { apiCall, psql, session } from "./request-helpers";

const RESTORE_APPROVE =
  "INSERT INTO role_permissions (role, permission_code) VALUES ('ADMIN', 'requests.approve') ON CONFLICT DO NOTHING";

// The permission is always restored: before the test (in case a previous run was killed mid-way),
// in `finally` around the scenario, and again in afterEach whatever the outcome.
test.beforeEach(() => psql(RESTORE_APPROVE));
test.afterEach(() => psql(RESTORE_APPROVE));

/**
 * RBAC is data-driven: removing `requests.approve` from the ADMIN role (directly in the real
 * PostgreSQL) immediately hides the action in the UI and makes the API refuse it.
 */
test("an admin without the approval permission cannot approve", async ({ browser }) => {
  test.setTimeout(120_000);
  const admin = await session(browser, accounts.admin, DEMO_PASSWORD);
  const student = await session(browser, accounts.student, DEMO_PASSWORD);

  const [enrollment] = (await (await apiCall(student, "GET", "/students/me/enrollments")).json()).filter(
    (e: { status: string }) => e.status === "VERIFIED",
  );
  const types = await (
    await apiCall(student, "GET", `/catalog/document-types?category_id=${enrollment.branch.category.id}`)
  ).json();
  const typeId = types.find((t: { code: string }) => t.code === "ATTESTATION_SCOLARITE").id;
  const created = await apiCall(student, "POST", "/requests", {
    multipart: { payload: JSON.stringify({ enrollment_id: enrollment.id, items: [{ document_type_id: typeId }] }) },
  });
  expect(created.status()).toBe(201);
  const { id } = await created.json();
  for (const to_status of ["IN_REVIEW", "PROCESSING"]) {
    expect((await apiCall(admin, "POST", `/admin/requests/${id}/transitions`, { data: { to_status } })).status()).toBe(200);
  }

  try {
    psql("DELETE FROM role_permissions WHERE role = 'ADMIN' AND permission_code = 'requests.approve'");
    await admin.goto(`/fr/admin/requests/${id}`);
    await expect(byTestId(admin, "transition-REJECTED")).toBeVisible();
    await expect(byTestId(admin, "transition-APPROVED")).toHaveCount(0);
    const res = await apiCall(admin, "POST", `/admin/requests/${id}/transitions`, { data: { to_status: "APPROVED" } });
    expect(res.status()).toBe(403);
  } finally {
    psql(RESTORE_APPROVE);
  }
  await admin.reload();
  await expect(byTestId(admin, "transition-APPROVED")).toBeVisible();

  await admin.context().close();
  await student.context().close();
});
