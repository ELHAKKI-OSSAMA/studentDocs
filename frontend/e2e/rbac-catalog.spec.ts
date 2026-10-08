import { expect, test } from "@playwright/test";
import { DEMO_PASSWORD, accounts, byTestId, expectNoRawKeys, login } from "./helpers";

test.beforeEach(() => {
  test.skip(!DEMO_PASSWORD, "SEED_DEMO_PASSWORD not set (demo accounts are not seeded)");
});

test("student: student area OK, admin area and admin API refused", async ({ page }) => {
  await login(page, accounts.student, DEMO_PASSWORD);
  await expect(page).toHaveURL(/\/fr\/student$/);
  // The seeded enrollment comes from PostgreSQL through the API.
  await expect(byTestId(page, "dashboard-enrollments")).toContainText("Intelligence artificielle");

  await page.goto("/fr/admin");
  await expect(page).toHaveURL(/\/fr\/student$/);

  const res = await page.request.get("/api/v1/admin/dashboard");
  expect(res.status()).toBe(403);
  const write = await page.request.post("/api/v1/admin/catalog/branch-categories", {
    data: { code: "HACK", name_i18n: { fr: "x" } },
    headers: { "X-CSRF-Token": (await page.context().cookies()).find((c) => c.name === "sd_csrf")!.value },
  });
  expect(write.status()).toBe(403);
});

test("admin: dashboard with real statistics, catalog is read-only", async ({ page }) => {
  await login(page, accounts.admin, DEMO_PASSWORD);
  await expect(page).toHaveURL(/\/fr\/admin$/);
  await expect(byTestId(page, "stat-doctypes")).toHaveText(/^\d+$/);
  expect(Number(await byTestId(page, "stat-doctypes").innerText())).toBeGreaterThanOrEqual(9);

  await page.goto("/fr/admin/document-types");
  await expect(byTestId(page, "catalog-rows")).toContainText("ATTESTATION_SCOLARITE");
  await expect(byTestId(page, "catalog-create")).toHaveCount(0);
  await expect(page.getByText("Lecture seule")).toBeVisible();

  // Super-admin-only areas are hidden and refused by the API.
  await expect(page.getByRole("link", { name: "Paramètres" })).toHaveCount(0);
  const res = await page.request.get("/api/v1/admin/settings/email-domains");
  expect(res.status()).toBe(403);
  await expectNoRawKeys(page);
});

test("super-admin: create, edit and delete a category from the UI", async ({ page }) => {
  const code = `E2E_${Date.now().toString(36).toUpperCase()}`;
  await login(page, accounts.superAdmin, DEMO_PASSWORD);
  await expect(page).toHaveURL(/\/fr\/admin$/);
  await page.goto("/fr/admin/branch-categories");

  // Create
  await byTestId(page, "catalog-create").click();
  const form = byTestId(page, "catalog-form");
  await form.locator("#f-code").fill(code);
  await form.locator("#f-name_i18n-fr").fill("Catégorie E2E");
  await form.locator("#f-name_i18n-en").fill("E2E category");
  await form.locator("#f-name_i18n-ar").fill("فئة الاختبار");
  await form.locator("button[type=submit]").click();
  const row = byTestId(page, "catalog-rows").getByRole("row").filter({ hasText: code });
  await expect(row).toContainText("Catégorie E2E");

  // Duplicate code → translated conflict error
  await byTestId(page, "catalog-create").click();
  await form.locator("#f-code").fill(code);
  await form.locator("#f-name_i18n-fr").fill("Doublon");
  await form.locator("button[type=submit]").click();
  await expect(form.locator("[data-slot=alert]")).toHaveText("Un élément avec ce code existe déjà.");
  await page.keyboard.press("Escape");

  // Edit (persisted: survives a reload)
  await row.getByRole("button", { name: "Modifier" }).click();
  await expect(form.locator("#f-code")).toBeDisabled();
  await form.locator("#f-name_i18n-fr").fill("Catégorie modifiée");
  await form.locator("button[type=submit]").click();
  await page.reload();
  await expect(row).toContainText("Catégorie modifiée");

  // Delete
  await row.getByRole("button", { name: "Supprimer" }).click();
  await byTestId(page, "confirm-delete").click();
  await expect(row).toHaveCount(0);
});

test("super-admin: an in-use category cannot be deleted", async ({ page }) => {
  await login(page, accounts.superAdmin, DEMO_PASSWORD);
  await expect(page).toHaveURL(/\/fr\/admin$/);
  await page.goto("/fr/admin/branch-categories");
  const row = byTestId(page, "catalog-rows").getByRole("row").filter({ hasText: "MASTER" });
  await row.getByRole("button", { name: "Supprimer" }).click();
  await byTestId(page, "confirm-delete").click();
  await expect(page.getByText("Cet élément est utilisé ailleurs")).toBeVisible();
  await expect(row).toHaveCount(1);
});
