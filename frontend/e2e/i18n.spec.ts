import { expect, test } from "@playwright/test";
import { DEMO_PASSWORD, accounts, byTestId, expectNoRawKeys, login } from "./helpers";

test("locale negotiation, switching, RTL and persistence", async ({ browser }) => {
  const context = await browser.newContext({ locale: "en-US" });
  const page = await context.newPage();

  // No prefix → negotiated from Accept-Language.
  await page.goto("/");
  await expect(page).toHaveURL(/\/en$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expectNoRawKeys(page);

  // Switch to Arabic → RTL.
  await byTestId(page, "language-switcher").click();
  await byTestId(page, "lang-ar").click();
  await expect(page).toHaveURL(/\/ar$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "ar");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("وثائقك الإدارية بكل بساطة");
  await expectNoRawKeys(page);

  // The choice persists: the cookie wins over Accept-Language on the next visit.
  await page.goto("/");
  await expect(page).toHaveURL(/\/ar$/);

  // Switch to French.
  await byTestId(page, "language-switcher").click();
  await byTestId(page, "lang-fr").click();
  await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
  await expect(page.locator("html")).toHaveAttribute("lang", "fr");
  await context.close();
});

test("every page renders without missing translation keys in FR, EN and AR", async ({ page }) => {
  test.skip(!DEMO_PASSWORD, "SEED_DEMO_PASSWORD not set");
  const publicPages = ["", "/login", "/register"];
  const adminPages = [
    "/admin", "/admin/students", "/admin/academic-years", "/admin/branch-categories", "/admin/branches",
    "/admin/study-levels", "/admin/document-types", "/admin/users", "/admin/settings", "/admin/requests",
    "/admin/enrollments", "/admin/notifications",
  ];
  const studentPages = [
    "/student", "/student/new-request", "/student/requests", "/student/documents", "/student/notifications",
    "/student/profile",
  ];
  for (const lang of ["fr", "en", "ar"]) {
    for (const path of publicPages) {
      await page.goto(`/${lang}${path}`);
      await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
      await expectNoRawKeys(page);
    }
  }
  await login(page, accounts.superAdmin, DEMO_PASSWORD);
  await expect(page).toHaveURL(/\/admin$/);
  for (const lang of ["fr", "en", "ar"]) {
    for (const path of adminPages) {
      await page.goto(`/${lang}${path}`);
      await expect(page.locator("main h1")).toBeVisible();
      await expect(page.locator("[aria-busy=true]")).toHaveCount(0);
      await expectNoRawKeys(page);
    }
  }
  await page.context().clearCookies();
  await login(page, accounts.student, DEMO_PASSWORD);
  for (const lang of ["fr", "en", "ar"]) {
    for (const path of studentPages) {
      await page.goto(`/${lang}${path}`);
      await expect(page.locator("main h1")).toBeVisible();
      await expect(page.locator("[aria-busy=true]")).toHaveCount(0);
      await expect(page.locator("html")).toHaveAttribute("dir", lang === "ar" ? "rtl" : "ltr");
      await expectNoRawKeys(page);
    }
  }
});

test("a signed-in user's language choice is saved on the account", async ({ page }) => {
  test.skip(!DEMO_PASSWORD, "SEED_DEMO_PASSWORD not set");
  await login(page, accounts.student, DEMO_PASSWORD, "fr");
  await expect(page).toHaveURL(/\/fr\/student$/);
  await byTestId(page, "language-switcher").click();
  await byTestId(page, "lang-ar").click();
  await expect(page).toHaveURL(/\/ar\/student$/);
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("مرحباً");
  await expect.poll(async () => (await (await page.request.get("/api/v1/auth/me")).json()).locale).toBe("ar");

  // Restore French for other tests.
  await byTestId(page, "language-switcher").click();
  await byTestId(page, "lang-fr").click();
  await expect(page).toHaveURL(/\/fr\/student$/);
  await expect.poll(async () => (await (await page.request.get("/api/v1/auth/me")).json()).locale).toBe("fr");
});
