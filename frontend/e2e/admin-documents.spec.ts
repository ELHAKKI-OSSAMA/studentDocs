import { expect, test, type Page } from "@playwright/test";
import { accounts, byTestId, DEMO_PASSWORD } from "./helpers";
import { apiCall, eicarPdf, headerStatus, pdf, psql, session } from "./request-helpers";

/**
 * Admin actions on documents, on the real stack (API → Celery worker → ClamAV → S3):
 * rescan a document whose scan failed, and replace an infected final document.
 */

/** Demo student request for a digital document, moved to APPROVED by the admin (API). */
async function approvedRequest(student: Page, admin: Page): Promise<string> {
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
  for (const to_status of ["IN_REVIEW", "PROCESSING", "APPROVED"]) {
    expect((await apiCall(admin, "POST", `/admin/requests/${id}/transitions`, { data: { to_status } })).status()).toBe(200);
  }
  return id;
}

async function uploadFinal(admin: Page, file: ReturnType<typeof pdf>) {
  await admin.getByTestId("issued-input").setInputFiles(file);
  await byTestId(admin, "issued-submit").click();
}

function issuedRow(admin: Page, filename: string) {
  return byTestId(admin, "document-row").filter({ hasText: filename });
}

async function issuedDocs(admin: Page, id: string) {
  const detail = await (await apiCall(admin, "GET", `/admin/requests/${id}`)).json();
  return detail.documents.filter((d: { kind: string }) => d.kind === "ISSUED");
}

test.describe.configure({ mode: "serial" });

test("admin rescans a document whose antivirus scan ended in ERROR", async ({ browser }) => {
  const student = await session(browser, accounts.student, DEMO_PASSWORD);
  const admin = await session(browser, accounts.admin, DEMO_PASSWORD);
  const id = await approvedRequest(student, admin);

  await admin.goto(`/fr/admin/requests/${id}`);
  await uploadFinal(admin, pdf("attestation-panne.pdf"));
  await expect(issuedRow(admin, "attestation-panne.pdf")).toHaveAttribute("data-scan", "CLEAN", { timeout: 60_000 });
  const [doc] = await issuedDocs(admin, id);

  // A past ClamAV outage (retries exhausted) is recorded as ERROR: reproduced here in the real database,
  // because waiting for a real outage would take the whole retry window (several minutes).
  psql(
    `UPDATE documents SET scan_status = 'ERROR', scan_detail = 'scanner_unavailable' WHERE id = '${doc.id}'`,
  );
  await admin.reload();
  const row = issuedRow(admin, "attestation-panne.pdf");
  await expect(row).toHaveAttribute("data-scan", "ERROR");
  await expect(row.getByTestId("scan-status")).toHaveText("Erreur d'analyse");
  await expect(row.getByTestId("download-document")).toHaveCount(0);
  const refused = await apiCall(admin, "GET", `/admin/requests/${id}/documents/${doc.id}/download`);
  expect(refused.status()).toBe(409);

  // Rescan from the UI: back to SCANNING, then the real worker + ClamAV scan it again.
  await row.getByTestId("rescan-document").click();
  await expect(row).toHaveAttribute("data-scan", "CLEAN", { timeout: 60_000 });
  await expect(row.getByTestId("rescan-document")).toHaveCount(0);
  const [after] = await issuedDocs(admin, id);
  expect(after.scan_status).toBe("CLEAN");
  expect(after.can_download).toBe(true);
  expect((await apiCall(admin, "GET", `/admin/requests/${id}/documents/${doc.id}/download`)).status()).toBe(200);

  await student.context().close();
  await admin.context().close();
});

test("admin replaces an infected final document with a clean one", async ({ browser }) => {
  const student = await session(browser, accounts.student, DEMO_PASSWORD);
  const admin = await session(browser, accounts.admin, DEMO_PASSWORD);
  const id = await approvedRequest(student, admin);

  await admin.goto(`/fr/admin/requests/${id}`);
  await uploadFinal(admin, eicarPdf("attestation-infectee.pdf"));
  const infected = issuedRow(admin, "attestation-infectee.pdf");
  await expect(infected).toHaveAttribute("data-scan", "INFECTED", { timeout: 60_000 });
  await expect(infected.getByTestId("scan-detail")).toContainText("Eicar");

  // It cannot be delivered.
  await byTestId(admin, "transition-DOCUMENT_AVAILABLE").click();
  await byTestId(admin, "confirm-transition").click();
  await expect(byTestId(admin, "transition-error")).toHaveText(
    "Le document final n'a pas encore été accepté par l'antivirus.",
  );
  await admin.keyboard.press("Escape");

  // Replace: delete the infected file, upload a clean one.
  const [bad] = await issuedDocs(admin, id);
  await infected.getByTestId("delete-document").click();
  await expect(infected).toHaveCount(0);
  await uploadFinal(admin, pdf("attestation-saine.pdf"));
  await expect(issuedRow(admin, "attestation-saine.pdf")).toHaveAttribute("data-scan", "CLEAN", { timeout: 60_000 });

  const docs = await issuedDocs(admin, id);
  expect(docs.map((d: { filename: string; scan_status: string }) => [d.filename, d.scan_status])).toEqual([
    ["attestation-saine.pdf", "CLEAN"],
  ]);
  expect((await apiCall(admin, "GET", `/admin/requests/${id}/documents/${bad.id}/download`)).status()).toBe(404);

  // Now it can be delivered, and the student gets the clean file.
  await byTestId(admin, "transition-DOCUMENT_AVAILABLE").click();
  await byTestId(admin, "confirm-transition").click();
  await expect(headerStatus(admin)).toHaveAttribute("data-status", "DOCUMENT_AVAILABLE");
  const own = await apiCall(student, "GET", `/requests/${id}/documents/${docs[0].id}/download`);
  expect(own.status()).toBe(200);
  expect((await own.body()).subarray(0, 5).toString()).toBe("%PDF-");

  await student.context().close();
  await admin.context().close();
});
