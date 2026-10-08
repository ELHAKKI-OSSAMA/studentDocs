import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { expect, type Browser, type Page } from "@playwright/test";
import { byTestId, login, readMail, uniqueEmail } from "./helpers";

export const PASSWORD = "E2e-password-2026";

/** A real (minimal) PDF: the backend sniffs the content, not the extension. */
export function pdf(name: string) {
  return {
    name,
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"),
  };
}

/** Registers a student through the API and confirms the email through the link sent to Mailpit. */
export async function registerStudent(page: Page, prefix: string, firstName = "Sara", lastName = "Idrissi") {
  const email = uniqueEmail(prefix);
  const res = await page.request.post("/api/v1/auth/register", {
    data: { email, password: PASSWORD, first_name: firstName, last_name: lastName, locale: "fr" },
  });
  expect(res.status()).toBe(202);
  const link = (await readMail(page, email)).text.match(/https?:\/\/\S+verify-email\?token=\S+/)![0];
  await page.goto(link);
  await expect(byTestId(page, "verify-success")).toBeVisible();
  return email;
}

/** Separate browser context = separate session cookies (student and admin side by side). */
export async function session(browser: Browser, email: string, password: string) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await login(page, email, password);
  return page;
}

/** Declares Master / Science des données / 1re année for 2026-2027 from the profile page. */
export async function declareEnrollment(page: Page) {
  await page.goto("/fr/student/profile");
  const form = byTestId(page, "enrollment-form");
  await form.locator("#academic_year_id").selectOption({ label: "2026-2027" });
  await form.locator("#category").selectOption({ label: "Master" });
  await form.locator("#branch_id").selectOption({ label: "Science des données" });
  await form.locator("#study_level_id").selectOption({ label: "1re année" });
  await form.locator("button[type=submit]").click();
  await expect(byTestId(page, "enrollments-table")).toContainText("En attente de vérification");
}

/** Admin decision from the enrollments review page. */
export async function reviewEnrollment(admin: Page, email: string, decision: "verify" | "reject", note = "") {
  await admin.goto("/fr/admin/enrollments");
  await byTestId(admin, "enrollment-search").fill(email);
  await byTestId(admin, "enrollment-search").press("Enter");
  const row = byTestId(admin, "enrollments-review-table").locator(`tr[data-email="${email}"]`);
  await row.getByTestId(`${decision}-enrollment`).click();
  if (note) await byTestId(admin, "review-note-input").fill(note);
  await byTestId(admin, "confirm-review").click();
}

/** Calls the API with the session cookies and the CSRF double-submit header, like the app does. */
export async function apiCall(
  page: Page,
  method: "GET" | "POST",
  path: string,
  options: { data?: unknown; multipart?: Record<string, string | ReturnType<typeof pdf>> } = {},
) {
  const csrf = (await page.context().cookies()).find((c) => c.name === "sd_csrf")?.value ?? "";
  return page.request.fetch(`/api/v1${path}`, {
    method,
    headers: method === "GET" ? {} : { "X-CSRF-Token": csrf },
    data: options.data,
    multipart: options.multipart,
  });
}

/** Header status of a request detail page (the first badge; the timeline ones come after). */
export function headerStatus(page: Page) {
  return byTestId(page, "request-status").first();
}

/** Runs SQL in the real PostgreSQL container (used to alter RBAC data for a negative scenario). */
export function psql(sql: string) {
  const root = join(__dirname, "..", "..");
  const user = process.env.POSTGRES_USER ?? "studentdocs";
  const db = process.env.POSTGRES_DB ?? "studentdocs";
  execFileSync("docker", ["compose", "exec", "-T", "postgres", "psql", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1", "-c", sql], {
    cwd: root,
    stdio: "pipe",
  });
}
