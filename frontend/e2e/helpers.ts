import { expect, type Page } from "@playwright/test";

export const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";
export const STUDENT_DOMAIN = process.env.SEED_STUDENT_EMAIL_DOMAIN ?? "etu.univ-demo.ma";
export const DEMO_PASSWORD = process.env.SEED_DEMO_PASSWORD ?? "";

export const accounts = {
  superAdmin: "superadmin@univ-demo.ma",
  admin: "admin@univ-demo.ma",
  student: `etudiant@${STUDENT_DOMAIN}`,
};

export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}@${STUDENT_DOMAIN}`;
}

/** Polls Mailpit until a message for `to` arrives and returns its plain-text body. */
export async function readMail(page: Page, to: string): Promise<{ subject: string; text: string }> {
  let found: { ID: string; Subject: string } | undefined;
  await expect
    .poll(
      async () => {
        const res = await page.request.get(`${MAILPIT}/api/v1/search`, { params: { query: `to:"${to}"` } });
        found = (await res.json()).messages?.[0];
        return !!found;
      },
      { timeout: 20_000 },
    )
    .toBe(true);
  const res = await page.request.get(`${MAILPIT}/api/v1/message/${found!.ID}`);
  const body = await res.json();
  return { subject: body.Subject, text: body.Text };
}

/** Submits the login form. With `expectSuccess`, waits until the app has left the login page. */
export async function login(
  page: Page,
  email: string,
  password: string,
  lang = "fr",
  { expectSuccess = true }: { expectSuccess?: boolean } = {},
) {
  await page.goto(`/${lang}/login`);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator("form button[type=submit]").click();
  if (expectSuccess) await expect(page).not.toHaveURL(/\/login/);
}

/** Visible-only test id lookup (Next keeps previously visited pages mounted but hidden). */
export function byTestId(page: Page, id: string) {
  return page.getByTestId(id).filter({ visible: true });
}

/** The app's alert component (Next's route announcer also uses role="alert"). */
export function appAlert(page: Page) {
  return page.locator("[data-slot=alert]").filter({ visible: true });
}

export async function logout(page: Page) {
  await byTestId(page, "user-menu").click();
  await byTestId(page, "logout").click();
  await expect(page).toHaveURL(/\/login$/);
}

/** Fails if a raw translation key (e.g. "nav.dashboard") is rendered instead of its text. */
export async function expectNoRawKeys(page: Page) {
  const text = await page.locator("body").innerText();
  const raw = text.match(/\b(app|common|errors|home|auth|nav|student|admin|catalog|users|students|settings|status|action|enrollmentStatus|requests|notifications|enrollments)\.[a-zA-Z_]+\b/g);
  expect(raw ?? []).toEqual([]);
}
