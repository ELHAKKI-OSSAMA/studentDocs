// @vitest-environment jsdom
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import NewRequestPage from "@/app/[lang]/student/new-request/page";
import type { DocumentType, Enrollment, EnrollmentStatus } from "@/lib/api/types";
import { renderWithProviders, stubFetch } from "@/test/render";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const CATEGORY = { id: "cat-1", code: "MASTER", name_i18n: { fr: "Master" } };

function enrollment(id: string, status: EnrollmentStatus, label: string): Enrollment {
  return {
    id,
    academic_year: { id: `y-${id}`, label, status: "ACTIVE" },
    branch: { id: "b1", code: "IA", name_i18n: { fr: "IA" }, category: CATEGORY },
    study_level: { id: "l1", code: "M1", name_i18n: { fr: "M1" } },
    status,
    source: "SELF_DECLARED",
    review_note: null,
    reviewed_at: null,
    created_at: "2026-09-01T00:00:00Z",
  };
}

function docType(id: string, name: string, overrides: Partial<DocumentType> = {}): DocumentType {
  return {
    id,
    code: id,
    name_i18n: { fr: name },
    description_i18n: null,
    delivery_mode: "DIGITAL",
    requires_attachment: false,
    max_quantity: 3,
    processing_days: 2,
    is_active: true,
    allowed_categories: [],
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

const TYPES = [
  docType("attestation", "Attestation de scolarité"),
  docType("convention", "Convention de stage", { requires_attachment: true, max_quantity: 1 }),
];

function setup(enrollments: Enrollment[]) {
  const { fetchMock, calls } = stubFetch([
    { path: "/api/v1/students/me/enrollments", body: enrollments },
    { path: "/api/v1/catalog/document-types", body: TYPES },
    {
      method: "POST",
      path: "/api/v1/requests",
      status: 201,
      body: { id: "3f2b8c1e-8a5d-4c1e-9b7a-1234567890ab", reference: "REQ-2026-000042" },
    },
  ]);
  vi.stubGlobal("fetch", fetchMock);
  renderWithProviders(<NewRequestPage />);
  return calls;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function chooseEnrollment(id: string) {
  const select = await screen.findByTestId("enrollment-select");
  fireEvent.change(select, { target: { value: id } });
  await screen.findAllByTestId("document-choice");
}

function choice(name: string) {
  return screen.getAllByTestId("document-choice").find((li) => li.textContent?.includes(name))!;
}

describe("New request form", () => {
  it("only offers VERIFIED enrollments", async () => {
    setup([
      enrollment("ok", "VERIFIED", "2026-2027"),
      enrollment("wait", "PENDING", "2025-2026"),
      enrollment("no", "REJECTED", "2024-2025"),
    ]);
    const select = await screen.findByTestId("enrollment-select");
    const values = Array.from(select.querySelectorAll("option")).map((o) => o.getAttribute("value"));
    expect(values).toEqual(["", "ok"]);
    expect(screen.getByText(/1 inscription\(s\) en attente de vérification/)).toBeTruthy();
  });

  it("explains what to do when no enrollment is verified", async () => {
    setup([enrollment("wait", "PENDING", "2025-2026"), enrollment("no", "REJECTED", "2024-2025")]);
    expect(await screen.findByTestId("no-verified-enrollment")).toBeTruthy();
    expect(screen.queryByTestId("new-request-form")).toBeNull();
  });

  it("shows each document's rules", async () => {
    setup([enrollment("ok", "VERIFIED", "2026-2027")]);
    await chooseEnrollment("ok");
    expect(choice("Convention de stage").textContent).toContain("Pièce justificative obligatoire");
    expect(choice("Attestation de scolarité").textContent).toContain("max. 3");
    expect(choice("Attestation de scolarité").textContent).toContain("Délai indicatif : 2 jours");
  });

  it("validates before submitting: nothing selected, then missing attachment", async () => {
    const calls = setup([enrollment("ok", "VERIFIED", "2026-2027")]);
    await chooseEnrollment("ok");
    fireEvent.click(screen.getByTestId("submit-request"));
    expect((await screen.findByTestId("form-errors")).textContent).toContain("Sélectionnez au moins un document.");

    fireEvent.click(screen.getByRole("checkbox", { name: "Convention de stage" }));
    fireEvent.click(screen.getByTestId("submit-request"));
    await waitFor(() =>
      expect(screen.getByTestId("form-errors").textContent).toContain("Ajoutez la pièce justificative obligatoire."),
    );
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("submits a multipart request with several documents and shows the reference", async () => {
    const calls = setup([enrollment("ok", "VERIFIED", "2026-2027")]);
    await chooseEnrollment("ok");
    fireEvent.click(screen.getByRole("checkbox", { name: "Attestation de scolarité" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Convention de stage" }));
    fireEvent.change(screen.getAllByTestId("document-quantity")[0], { target: { value: "2" } });
    const file = new File(["%PDF-1.4"], "convention.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByTestId("attachment-input"), { target: { files: [file] } });
    fireEvent.click(screen.getByTestId("submit-request"));

    expect((await screen.findByTestId("request-reference")).textContent).toBe("REQ-2026-000042");
    const post = calls.find((c) => c.method === "POST")!;
    const body = post.init.body as FormData;
    expect(JSON.parse(String(body.get("payload"))).items).toEqual([
      { document_type_id: "attestation", quantity: 2 },
      { document_type_id: "convention", quantity: 1 },
    ]);
    expect((body.get("attachment:convention") as File).name).toBe("convention.pdf");
    // The browser sets the multipart boundary: no JSON content type is forced.
    expect((post.init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });

  it("shows a translated API error", async () => {
    const { fetchMock } = stubFetch([
      { path: "/api/v1/students/me/enrollments", body: [enrollment("ok", "VERIFIED", "2026-2027")] },
      { path: "/api/v1/catalog/document-types", body: TYPES },
      {
        method: "POST",
        path: "/api/v1/requests",
        status: 422,
        body: { error: { code: "enrollment_not_verified", message: "raw" } },
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(<NewRequestPage />);
    await chooseEnrollment("ok");
    fireEvent.click(screen.getByRole("checkbox", { name: "Attestation de scolarité" }));
    fireEvent.click(screen.getByTestId("submit-request"));
    expect((await screen.findByTestId("form-errors")).textContent).toContain(
      "Cette inscription n'a pas encore été vérifiée par l'administration.",
    );
  });
});
