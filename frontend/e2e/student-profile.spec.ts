import { expect, test } from "@playwright/test";
import { byTestId, login, readMail, uniqueEmail } from "./helpers";

test("student declares and removes an enrollment from catalog data", async ({ page }) => {
  // Fresh student so the test does not depend on (or modify) seeded enrollments.
  const email = uniqueEmail("enroll");
  const password = "E2e-password-2026";
  const res = await page.request.post("/api/v1/auth/register", {
    data: { email, password, first_name: "Sara", last_name: "Idrissi", locale: "fr" },
  });
  expect(res.status()).toBe(202);
  const link = (await readMail(page, email)).text.match(/https?:\/\/\S+verify-email\?token=\S+/)![0];
  await page.goto(link);
  await expect(byTestId(page, "verify-success")).toBeVisible();

  await login(page, email, password);
  await page.goto("/fr/student/profile");
  await expect(page.getByText("Aucune inscription déclarée.").first()).toBeVisible();

  const form = byTestId(page, "enrollment-form");
  await form.locator("#academic_year_id").selectOption({ label: "2026-2027" });
  await form.locator("#category").selectOption({ label: "Master" });
  await form.locator("#branch_id").selectOption({ label: "Science des données" });
  await form.locator("#study_level_id").selectOption({ label: "2e année" });
  await form.locator("button[type=submit]").click();

  const table = byTestId(page, "enrollments-table");
  await expect(table).toContainText("Science des données");
  await page.reload();
  await expect(table).toContainText("2026-2027");

  await table.getByRole("button", { name: "Supprimer" }).click();
  await expect(table).toHaveCount(0);
});
