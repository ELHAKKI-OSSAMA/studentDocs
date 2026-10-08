import { expect, test, type Page } from "@playwright/test";
import { accounts, byTestId, DEMO_PASSWORD } from "./helpers";
import { apiCall, eicarPdf, pdf, session } from "./request-helpers";

/**
 * Phase 3 — secure document pipeline, end to end on the real stack:
 * browser → API (validation, SHA-256, private S3) → Celery worker → ClamAV → status → authorized download.
 */

async function newRequest(student: Page, file: { name: string; mimeType: string; buffer: Buffer }) {
  await student.goto("/fr/student/new-request");
  await byTestId(student, "enrollment-select").selectOption({ index: 1 });
  await student.getByRole("checkbox", { name: "Certificat de stage" }).click();
  await student.getByTestId("attachment-input").setInputFiles(file);
  await byTestId(student, "submit-request").click();
}

async function openCreatedRequest(student: Page) {
  // Never "accepted" right away: the confirmation says the file is being scanned.
  await expect(byTestId(student, "scan-pending-notice")).toContainText("analyse antivirus en cours");
  await byTestId(student, "request-created").getByRole("link", { name: "Voir la demande" }).click();
  await expect(byTestId(student, "document-row")).toHaveCount(1);
  return student.url().split("/").pop()!;
}

test.describe.configure({ mode: "serial" });

test("a clean PDF is scanned, accepted, then downloadable", async ({ browser }) => {
  const student = await session(browser, accounts.student, DEMO_PASSWORD);
  await newRequest(student, pdf("lettre-stage.pdf"));
  await openCreatedRequest(student);

  const row = byTestId(student, "document-row");
  // The page polls while the worker scans the file with ClamAV.
  await expect(row).toHaveAttribute("data-scan", "CLEAN", { timeout: 60_000 });
  await expect(row.getByTestId("scan-status")).toHaveText("Accepté");
  const [download] = await Promise.all([
    student.waitForEvent("download"),
    row.getByTestId("download-document").click(),
  ]);
  expect(download.suggestedFilename()).toBe("lettre-stage.pdf");
  await student.context().close();
});

test("an infected PDF (EICAR) is rejected, quarantined and never downloadable", async ({ browser }) => {
  const student = await session(browser, accounts.student, DEMO_PASSWORD);
  const admin = await session(browser, accounts.admin, DEMO_PASSWORD);
  await newRequest(student, eicarPdf("attestation.pdf"));
  const requestId = await openCreatedRequest(student);

  const row = byTestId(student, "document-row");
  await expect(row).toHaveAttribute("data-scan", "INFECTED", { timeout: 60_000 });
  await expect(row.getByTestId("scan-status")).toHaveText("Rejeté : menace détectée");
  await expect(row.getByTestId("scan-explanation")).toContainText("ne sera jamais transmis");
  await expect(row.getByTestId("download-document")).toHaveCount(0);

  // The API refuses it too (fail closed), for the owner and for staff.
  const docs = (await (await apiCall(student, "GET", `/requests/${requestId}`)).json()).documents;
  const own = await apiCall(student, "GET", `/requests/${requestId}/documents/${docs[0].id}/download`);
  expect(own.status()).toBe(409);
  expect((await own.json()).error.code).toBe("document_not_available");
  expect((await apiCall(admin, "GET", `/admin/requests/${requestId}/documents/${docs[0].id}/download`)).status()).toBe(409);
  expect(JSON.stringify(docs)).not.toContain("storage_key");

  // The student is notified in-app; staff see the detected signature.
  await student.goto("/fr/student/notifications");
  await expect(byTestId(student, "notification-list")).toContainText("rejeté par l'antivirus");
  await admin.goto(`/fr/admin/requests/${requestId}`);
  await expect(byTestId(admin, "scan-detail")).toContainText("Eicar");

  await student.context().close();
  await admin.context().close();
});

test("falsified files are refused before storage", async ({ browser }) => {
  const student = await session(browser, accounts.student, DEMO_PASSWORD);
  // PDF content presented as a PNG image (consistent name and type, inconsistent content).
  await newRequest(student, { ...pdf("photo.png"), mimeType: "image/png" });
  await expect(byTestId(student, "form-errors")).toContainText("L'extension du fichier ne correspond pas à son contenu.");

  // An executable renamed to .pdf: refused on its content (magic bytes).
  const exe = { name: "document.pdf", mimeType: "application/pdf", buffer: Buffer.from("MZ\x90\x00 fake executable") };
  await newRequest(student, exe);
  await expect(byTestId(student, "form-errors")).toContainText("seuls les fichiers PDF, PNG et JPEG sont acceptés");
  await student.context().close();
});
