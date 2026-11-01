import { expect, test } from "@playwright/test";
import { accounts, byTestId, DEMO_PASSWORD } from "./helpers";
import { declareEnrollment, PASSWORD, registerStudent, reviewEnrollment, session } from "./request-helpers";

const WITHDRAWAL = "Retrait du baccalauréat (original)";

test("a student can only withdraw an original the administration holds; the admin sees the student's file", async ({
  browser,
  page,
}) => {
  test.setTimeout(180_000);
  const email = await registerStudent(page, "deposit", "Imane", "Tazi");
  const student = await session(browser, email, PASSWORD);
  const admin = await session(browser, accounts.admin, DEMO_PASSWORD);
  await declareEnrollment(student);
  await reviewEnrollment(admin, email, "verify", "Dossier complet");

  // Nothing deposited yet: the withdrawal is not offered.
  await student.goto("/fr/student/new-request");
  await byTestId(student, "enrollment-select").selectOption({ index: 1 });
  await expect(student.getByRole("checkbox", { name: "Attestation de scolarité" })).toBeVisible();
  await expect(student.getByRole("checkbox", { name: WITHDRAWAL })).toHaveCount(0);

  // The administration opens the student's file from the list and records the deposited baccalaureate.
  await admin.goto("/fr/admin/students");
  await admin.getByRole("searchbox").fill(email);
  await byTestId(admin, "student-link").first().click();
  await expect(byTestId(admin, "student-detail")).toContainText("Imane Tazi");
  await expect(byTestId(admin, "student-enrollments")).toContainText("Vérifiée");
  await admin.locator("#deposit-type").selectOption({ label: WITHDRAWAL });
  await admin.locator("#deposit-date").fill("2023-09-12");
  await byTestId(admin, "deposit-form").getByRole("button").click();
  await expect(byTestId(admin, "deposit-row")).toContainText("Détenu");

  // Now the student can ask for it back.
  await student.reload();
  await byTestId(student, "enrollment-select").selectOption({ index: 1 });
  await student.getByRole("checkbox", { name: WITHDRAWAL }).click();
  await expect(byTestId(student, "deposit-info")).toContainText("2023");
  await byTestId(student, "submit-request").click();
  const reference = (await byTestId(student, "request-reference").innerText()).trim();

  // The request appears in the student's history on the admin side.
  await admin.reload();
  await expect(byTestId(admin, "student-requests")).toContainText(reference);

  // Once returned, the original can no longer be requested; the deposit stays in the history.
  await byTestId(admin, "deposit-return").click();
  await expect(byTestId(admin, "deposit-row")).toContainText("Rendu le");
  await student.goto("/fr/student/new-request");
  await byTestId(student, "enrollment-select").selectOption({ index: 1 });
  await expect(student.getByRole("checkbox", { name: "Attestation de scolarité" })).toBeVisible();
  await expect(student.getByRole("checkbox", { name: WITHDRAWAL })).toHaveCount(0);
});
