import { expect, test } from "@playwright/test";
import { DEMO_PASSWORD, accounts, appAlert, byTestId, login, logout, readMail, uniqueEmail } from "./helpers";

test("student: register → verify email → login → session refresh → logout", async ({ page, context }) => {
  const email = uniqueEmail("signup");
  const password = "E2e-password-2026";

  // Register through the UI.
  await page.goto("/fr/register");
  await page.locator("#first_name").fill("Ahmed");
  await page.locator("#last_name").fill("Alaoui");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator("form button[type=submit]").click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Vérifiez votre boîte email");

  // Login before verification is refused.
  await login(page, email, password, "fr", { expectSuccess: false });
  await expect(appAlert(page)).toContainText("confirmer votre adresse email");

  // The verification email is really delivered; follow its link.
  const mail = await readMail(page, email);
  expect(mail.subject).toBe("Confirmez votre adresse email");
  const link = mail.text.match(/https?:\/\/\S+verify-email\?token=\S+/)![0];
  await page.goto(link);
  await expect(byTestId(page, "verify-success")).toBeVisible();

  // Login → student dashboard.
  await login(page, email, password);
  await expect(page).toHaveURL(/\/fr\/student$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Bonjour Ahmed, voici vos demandes.");

  // Simulate an expired access token: the client refreshes the session transparently.
  const cookies = await context.cookies();
  expect(cookies.find((c) => c.name === "sd_access")?.httpOnly).toBe(true);
  expect(cookies.find((c) => c.name === "sd_refresh")?.httpOnly).toBe(true);
  const oldRefresh = cookies.find((c) => c.name === "sd_refresh")!.value;
  await context.clearCookies({ name: "sd_access" });
  await page.goto("/fr/student/profile");
  await expect(page.locator("#first_name")).toHaveValue("Ahmed");
  const rotated = (await context.cookies()).find((c) => c.name === "sd_refresh")!.value;
  expect(rotated).not.toBe(oldRefresh);

  // Logout → protected pages redirect to login.
  await logout(page);
  await page.goto("/fr/student");
  await expect(page).toHaveURL(/\/fr\/login\?next=%2Ffr%2Fstudent$/);
});

test("registration with a non-institutional email is refused", async ({ page }) => {
  await page.goto("/en/register");
  await page.locator("#first_name").fill("Test");
  await page.locator("#last_name").fill("User");
  await page.locator("#email").fill(`someone-${Date.now()}@example.com`);
  await page.locator("#password").fill("E2e-password-2026");
  await page.locator("form button[type=submit]").click();
  await expect(appAlert(page)).toContainText("institutional email");
});

test("wrong password shows a generic error", async ({ page }) => {
  await login(page, accounts.student, "Wrong-password-1", "en", { expectSuccess: false });
  await expect(appAlert(page)).toHaveText("Incorrect email or password.");
});

test("after login the user returns to the page they asked for", async ({ page }) => {
  test.skip(!DEMO_PASSWORD, "SEED_DEMO_PASSWORD not set");
  await page.goto("/fr/student/profile");
  await expect(page).toHaveURL(/\/fr\/login\?next=/);
  await page.locator("#email").fill(accounts.student);
  await page.locator("#password").fill(DEMO_PASSWORD);
  await page.locator("form button[type=submit]").click();
  await expect(page).toHaveURL(/\/fr\/student\/profile$/);
});
