import { expect, test } from "@playwright/test";
import { accounts, byTestId, DEMO_PASSWORD, readMail, uniqueEmail } from "./helpers";
import { session } from "./request-helpers";

// The test stack ignores the saved relay (SMTP_USE_DATABASE_SETTINGS=false) and this scenario never saves:
// the configuration a super-admin stored in the shared database is left untouched.
test("the super-admin tests an SMTP relay from the settings; an admin has no access", async ({ browser }) => {
  test.setTimeout(120_000);
  const superAdmin = await session(browser, accounts.superAdmin, DEMO_PASSWORD);
  await superAdmin.goto("/fr/admin/settings");
  const card = byTestId(superAdmin, "smtp-settings");
  await expect(card).toBeVisible();
  await expect(byTestId(superAdmin, "smtp-database-disabled")).toBeVisible();
  await expect(byTestId(superAdmin, "smtp-active-source")).toContainText(".env");

  // Mailpit relay (no TLS, no login): a real SMTP delivery that stays local.
  await card.locator("#smtp-security").selectOption("NONE");
  await card.locator("#smtp-host").fill("mailpit");
  await card.locator("#smtp-port").fill("1025");
  await card.locator("#smtp-username").fill("");
  await card.locator("#smtp-from").fill("Scolarité E2E <scolarite-e2e@univ-demo.ma>");
  const to = uniqueEmail("smtp");
  await card.locator("#smtp-test-to").fill(to);
  await byTestId(superAdmin, "smtp-test").click();
  await expect(byTestId(superAdmin, "smtp-test-result")).toHaveAttribute("data-ok", "true");
  expect((await readMail(superAdmin, to)).subject).toContain("test SMTP");

  // A wrong port gives a readable error.
  await card.locator("#smtp-port").fill("9");
  await byTestId(superAdmin, "smtp-test").click();
  await expect(byTestId(superAdmin, "smtp-test-result")).toContainText("Connexion au serveur SMTP impossible");

  const admin = await session(browser, accounts.admin, DEMO_PASSWORD);
  expect((await admin.request.get("/api/v1/admin/settings/smtp")).status()).toBe(403);
});
