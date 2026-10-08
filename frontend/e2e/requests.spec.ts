import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { accounts, appAlert, byTestId, DEMO_PASSWORD } from "./helpers";
import {
  apiCall,
  declareEnrollment,
  headerStatus,
  PASSWORD,
  pdf,
  registerStudent,
  reviewEnrollment,
  session,
} from "./request-helpers";

const REFERENCE = /^REQ-\d{4}-\d{6}$/;

async function transition(admin: Page, status: string, comment?: string) {
  await byTestId(admin, `transition-${status}`).click();
  if (comment) await byTestId(admin, "transition-comment").fill(comment);
  await byTestId(admin, "confirm-transition").click();
  await expect(headerStatus(admin)).toHaveAttribute("data-status", status);
}

test.describe.configure({ mode: "serial" });

test("full request lifecycle between a student and the administration", async ({ browser, page }) => {
  test.setTimeout(240_000);

  // 1. The student registers, confirms the email and signs in.
  const email = await registerStudent(page, "flow", "Nadia", "Berrada");
  const student = await session(browser, email, PASSWORD);
  const admin = await session(browser, accounts.admin, DEMO_PASSWORD);

  // 2. Declared enrollment is PENDING: it cannot back a request yet.
  await declareEnrollment(student);
  await student.goto("/fr/student/new-request");
  await expect(byTestId(student, "no-verified-enrollment")).toBeVisible();

  // The administration verifies it; the reviewer and date are shown.
  await reviewEnrollment(admin, email, "verify", "Vérifié sur Apogée");
  await byTestId(admin, "enrollment-status-filter").selectOption("VERIFIED");
  const reviewed = byTestId(admin, "enrollments-review-table").locator(`tr[data-email="${email}"]`);
  await expect(reviewed.getByTestId("review-info")).toContainText("Youssef Amrani");
  await expect(reviewed.getByTestId("review-info")).toContainText("Vérifié sur Apogée");
  await student.goto("/fr/student/profile");
  await expect(byTestId(student, "enrollments-table")).toContainText("Vérifiée");

  // 3-6. Request with several documents; the supporting document is required before submission.
  await student.goto("/fr/student/new-request");
  await byTestId(student, "enrollment-select").selectOption({ index: 1 });
  await student.getByRole("checkbox", { name: "Attestation de scolarité" }).click();
  await student.getByRole("checkbox", { name: "Certificat de stage" }).click();
  await byTestId(student, "document-quantity").first().fill("2");
  await byTestId(student, "submit-request").click();
  await expect(byTestId(student, "form-errors")).toContainText("Ajoutez la pièce justificative obligatoire.");

  await student.getByTestId("attachment-input").setInputFiles(pdf("lettre-stage.pdf"));
  await byTestId(student, "submit-request").click();
  const reference = (await byTestId(student, "request-reference").innerText()).trim();
  expect(reference).toMatch(REFERENCE);

  // 7. Visible in "Mes demandes" with the RECEIVED status.
  await student.goto("/fr/student/requests");
  const row = byTestId(student, "requests-table").locator(`tr[data-reference="${reference}"]`);
  await expect(row.getByTestId("request-status")).toHaveText("Reçue");
  await row.getByRole("link", { name: reference }).click();
  await expect(byTestId(student, "cancel-request")).toBeVisible(); // still cancellable at RECEIVED
  await expect(byTestId(student, "timeline")).toContainText("Envoyée");
  const requestId = student.url().split("/").pop()!;

  // 8. The administration finds it (search by reference) and opens it.
  await admin.goto("/fr/admin/requests");
  await byTestId(admin, "request-search").fill(reference);
  await byTestId(admin, "request-search").press("Enter");
  await byTestId(admin, "admin-requests-table").getByRole("link", { name: reference }).click();
  await expect(byTestId(admin, "student-name")).toHaveText("Nadia Berrada");
  await expect(byTestId(admin, "document-list")).toContainText("lettre-stage.pdf");

  // 9. Manual assignment.
  await byTestId(admin, "assignee-select").selectOption({ label: "Youssef Amrani" });
  await byTestId(admin, "assign-save").click();
  await expect(byTestId(admin, "assigned-to")).toHaveText("Youssef Amrani");

  // 10. RECEIVED → IN_REVIEW: the student can no longer cancel (UI and API).
  await transition(admin, "IN_REVIEW");
  await student.reload();
  await expect(headerStatus(student)).toHaveAttribute("data-status", "IN_REVIEW");
  await expect(byTestId(student, "cancel-request")).toHaveCount(0);
  const lateCancel = await apiCall(student, "POST", `/requests/${requestId}/cancel`);
  expect(lateCancel.status()).toBe(409);
  expect((await lateCancel.json()).error.code).toBe("transition_not_allowed");

  // 11. Information request (mandatory comment, visible to the student).
  await transition(admin, "NEEDS_INFORMATION", "Merci de joindre la convention signée par l'entreprise.");

  // 12. The student sees the notification.
  await student.goto("/fr/student");
  await expect(byTestId(student, "notification-count")).toBeVisible();
  await student.goto("/fr/student/notifications");
  const note = byTestId(student, "notification-list").getByText(
    `Une information est demandée pour la demande ${reference}.`,
  );
  await note.click();
  await expect(byTestId(student, "information-needed")).toBeVisible();
  await expect(byTestId(student, "message-list")).toContainText("convention signée");

  // 13. The student answers with a file: the request goes back to review.
  await byTestId(student, "message-input").fill("Voici la convention signée.");
  await student.getByTestId("message-files").setInputFiles(pdf("convention-signee.pdf"));
  await byTestId(student, "message-send").click();
  await expect(headerStatus(student)).toHaveAttribute("data-status", "IN_REVIEW");
  await expect(byTestId(student, "message-list")).toContainText("Voici la convention signée.");

  // 14-16. The administration reads the answer and resumes: PROCESSING → APPROVED.
  await admin.reload();
  await expect(headerStatus(admin)).toHaveAttribute("data-status", "IN_REVIEW");
  await expect(byTestId(admin, "message-list")).toContainText("convention-signee.pdf");
  await byTestId(admin, "message-input").fill("Bien reçu, merci.");
  await byTestId(admin, "message-send").click();
  await expect(byTestId(admin, "message-list")).toContainText("Bien reçu, merci.");
  await transition(admin, "PROCESSING");
  await transition(admin, "APPROVED");

  // The final document is required before DOCUMENT_AVAILABLE.
  await byTestId(admin, "transition-DOCUMENT_AVAILABLE").click();
  await byTestId(admin, "confirm-transition").click();
  await expect(byTestId(admin, "transition-error")).toHaveText("Déposez d'abord le document final.");
  await admin.keyboard.press("Escape");

  // 17. Upload of the final document (hidden from the student until it is made available).
  await admin.getByTestId("issued-input").setInputFiles(pdf("attestation-finale.pdf"));
  await byTestId(admin, "issued-submit").click();
  await expect(byTestId(admin, "document-list").locator("[data-kind=ISSUED]")).toContainText("attestation-finale.pdf");
  await student.reload();
  await expect(byTestId(student, "document-list").locator("[data-kind=ISSUED]")).toHaveCount(0);

  // 18. DOCUMENT_AVAILABLE (all items are digital).
  await transition(admin, "DOCUMENT_AVAILABLE");

  // 19. The student downloads it through the authorized endpoint.
  await student.goto("/fr/student/documents");
  const issued = byTestId(student, "issued-documents");
  await expect(issued).toContainText(reference);
  const [download] = await Promise.all([
    student.waitForEvent("download"),
    issued.locator("[data-kind=ISSUED]").getByTestId("download-document").click(),
  ]);
  expect(download.suggestedFilename()).toBe("attestation-finale.pdf");
  expect(readFileSync(await download.path()).subarray(0, 5).toString()).toBe("%PDF-");

  // 20. COMPLETED.
  await transition(admin, "COMPLETED");
  await student.goto(`/fr/student/requests/${requestId}`);
  await expect(headerStatus(student)).toHaveText("Terminée");
  await expect(byTestId(student, "timeline")).toContainText("Document disponible");

  await student.context().close();
  await admin.context().close();
});

test.describe("negative scenarios", () => {
  test("a rejected enrollment is never selectable and the rejection needs a reason", async ({ browser, page }) => {
    const email = await registerStudent(page, "rejected");
    const student = await session(browser, email, PASSWORD);
    const admin = await session(browser, accounts.admin, DEMO_PASSWORD);
    await declareEnrollment(student);

    await reviewEnrollment(admin, email, "reject");
    await expect(byTestId(admin, "review-error")).toHaveText("Un message est obligatoire.");
    await byTestId(admin, "review-note-input").fill("Inscription introuvable sur Apogée.");
    await byTestId(admin, "confirm-review").click();
    await expect(byTestId(admin, "enrollments-review-table")).toHaveCount(0); // left the PENDING queue

    await student.goto("/fr/student/profile");
    await expect(byTestId(student, "review-note")).toContainText("Inscription introuvable sur Apogée.");
    await student.goto("/fr/student/new-request");
    await expect(byTestId(student, "no-verified-enrollment")).toBeVisible();

    // The API refuses it as well (not only the UI).
    const [enrollment] = await (await apiCall(student, "GET", "/students/me/enrollments")).json();
    const res = await apiCall(student, "POST", "/requests", {
      multipart: { payload: JSON.stringify({ enrollment_id: enrollment.id, items: [{ document_type_id: enrollment.id }] }) },
    });
    expect((await res.json()).error.code).toBe("enrollment_not_verified");
    await student.context().close();
    await admin.context().close();
  });

  test("isolation between students, forbidden actions and invalid references", async ({ browser, page }) => {
    test.setTimeout(120_000);
    // Student A: fresh account with a verified enrollment and a request.
    const email = await registerStudent(page, "alice");
    const alice = await session(browser, email, PASSWORD);
    const admin = await session(browser, accounts.admin, DEMO_PASSWORD);
    await declareEnrollment(alice);
    await reviewEnrollment(admin, email, "verify");

    const [enrollment] = await (await apiCall(alice, "GET", "/students/me/enrollments")).json();
    const types = await (
      await apiCall(alice, "GET", `/catalog/document-types?category_id=${enrollment.branch.category.id}`)
    ).json();
    const byCode = (code: string) => types.find((t: { code: string }) => t.code === code).id;

    // Required supporting document missing → refused by the backend.
    const missing = await apiCall(alice, "POST", "/requests", {
      multipart: {
        payload: JSON.stringify({ enrollment_id: enrollment.id, items: [{ document_type_id: byCode("CERTIFICAT_STAGE") }] }),
      },
    });
    expect(missing.status()).toBe(422);
    expect((await missing.json()).error.code).toBe("attachment_required");

    const created = await apiCall(alice, "POST", "/requests", {
      multipart: {
        payload: JSON.stringify({ enrollment_id: enrollment.id, items: [{ document_type_id: byCode("CERTIFICAT_STAGE") }] }),
        [`attachment:${byCode("CERTIFICAT_STAGE")}`]: pdf("piece.pdf"),
      },
    });
    expect(created.status()).toBe(201);
    const request = await created.json();
    const docId = request.documents[0].id;

    // Student B (seeded demo student) cannot see, download from or write to A's request: 404 everywhere.
    const bob = await session(browser, accounts.student, DEMO_PASSWORD);
    for (const res of [
      await apiCall(bob, "GET", `/requests/${request.id}`),
      await apiCall(bob, "GET", `/requests/${request.id}/documents/${docId}/download`),
      await apiCall(bob, "GET", `/requests/${request.id}/messages`),
      await apiCall(bob, "POST", `/requests/${request.id}/messages`, { multipart: { body: "Bonjour" } }),
      await apiCall(bob, "POST", `/requests/${request.id}/cancel`),
    ]) {
      expect(res.status()).toBe(404);
    }
    await bob.goto(`/fr/student/requests/${request.id}`);
    await expect(appAlert(bob)).toContainText("Élément introuvable.");

    // A student cannot change a status or reach any admin endpoint.
    const forced = await apiCall(alice, "POST", `/admin/requests/${request.id}/transitions`, {
      data: { to_status: "APPROVED" },
    });
    expect(forced.status()).toBe(403);
    expect([404, 405]).toContain(
      (await apiCall(alice, "POST", `/requests/${request.id}/transitions`, { data: { to_status: "COMPLETED" } })).status(),
    );
    expect((await apiCall(alice, "GET", "/admin/requests")).status()).toBe(403);
    await alice.goto("/fr/admin/requests");
    await expect(alice).not.toHaveURL(/\/admin/);

    // Invalid references: never sent to the API from the UI, rejected by the API.
    await alice.goto("/fr/student/requests/REQ-2026-999999");
    await expect(appAlert(alice)).toContainText("Élément introuvable.");
    expect((await apiCall(alice, "GET", "/requests/REQ-2026-999999")).status()).toBe(422);
    expect((await apiCall(alice, "GET", "/requests/00000000-0000-0000-0000-000000000000")).status()).toBe(404);

    // Rejection without a reason is refused (UI and API); with a reason the student sees it.
    await admin.goto(`/fr/admin/requests/${request.id}`);
    await byTestId(admin, "transition-REJECTED").click();
    await byTestId(admin, "confirm-transition").click();
    await expect(byTestId(admin, "transition-error")).toHaveText("Un message est obligatoire.");
    const bare = await apiCall(admin, "POST", `/admin/requests/${request.id}/transitions`, {
      data: { to_status: "REJECTED" },
    });
    expect((await bare.json()).error.code).toBe("message_required");
    await byTestId(admin, "transition-comment").fill("Document non conforme.");
    await byTestId(admin, "confirm-transition").click();
    await expect(headerStatus(admin)).toHaveAttribute("data-status", "REJECTED");
    await alice.goto(`/fr/student/requests/${request.id}`);
    await expect(byTestId(alice, "status-reason")).toContainText("Document non conforme.");

    for (const p of [alice, bob, admin]) await p.context().close();
  });
});
