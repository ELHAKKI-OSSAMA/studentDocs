import { describe, expect, it } from "vitest";
import { dispositionFilename } from "@/lib/api/client";
import type { DocumentType } from "@/lib/api/types";
import {
  buildMessageForm,
  buildRequestForm,
  commentRequired,
  fileProblem,
  isDestructive,
  isUuid,
  MAX_UPLOAD_BYTES,
  statusTone,
  validateDraft,
  type NewRequestDraft,
} from "@/lib/requests";

function docType(id: string, overrides: Partial<DocumentType> = {}): DocumentType {
  return {
    id,
    code: id.toUpperCase(),
    name_i18n: { fr: id },
    description_i18n: null,
    delivery_mode: "DIGITAL",
    requires_attachment: false,
    requires_deposit: false,
    max_quantity: 3,
    processing_days: 2,
    is_active: true,
    allowed_categories: [],
    created_at: "",
    updated_at: "",
    ...overrides,
  };
}

const pdf = () => new File(["%PDF-1.4"], "piece.pdf", { type: "application/pdf" });
const TYPES = [docType("attestation"), docType("convention", { requires_attachment: true, max_quantity: 1 })];

describe("validateDraft", () => {
  it("requires an enrollment and at least one document", () => {
    expect(validateDraft({ enrollmentId: "", selection: {} }, TYPES)).toEqual([
      "requests.selectEnrollment",
      "requests.selectAtLeastOne",
    ]);
  });

  it("requires the supporting document when the type demands it", () => {
    const draft: NewRequestDraft = { enrollmentId: "e1", selection: { convention: { quantity: 1, file: null } } };
    expect(validateDraft(draft, TYPES)).toEqual(["requests.missingAttachment"]);
    draft.selection.convention.file = pdf();
    expect(validateDraft(draft, TYPES)).toEqual([]);
  });

  it("enforces the per-document quantity bounds", () => {
    expect(validateDraft({ enrollmentId: "e1", selection: { attestation: { quantity: 4 } } }, TYPES)).toEqual([
      "errors.quantity_exceeded",
    ]);
    expect(validateDraft({ enrollmentId: "e1", selection: { attestation: { quantity: 0 } } }, TYPES)).toEqual([
      "errors.quantity_exceeded",
    ]);
    expect(validateDraft({ enrollmentId: "e1", selection: { attestation: { quantity: 3 } } }, TYPES)).toEqual([]);
  });

  it("refuses document types that are not offered for the enrollment", () => {
    expect(validateDraft({ enrollmentId: "e1", selection: { unknown: { quantity: 1 } } }, TYPES)).toEqual([
      "errors.document_type_not_allowed",
    ]);
  });

  it("checks the attached file type", () => {
    const exe = new File(["MZ"], "virus.exe", { type: "application/x-msdownload" });
    expect(validateDraft({ enrollmentId: "e1", selection: { convention: { quantity: 1, file: exe } } }, TYPES)).toEqual([
      "errors.file_name_not_allowed",
    ]);
    const txt = new File(["hello"], "notes.txt", { type: "text/plain" });
    expect(validateDraft({ enrollmentId: "e1", selection: { convention: { quantity: 1, file: txt } } }, TYPES)).toEqual([
      "errors.file_type_not_allowed",
    ]);
  });
});

describe("fileProblem", () => {
  it("accepts PDF, PNG and JPEG under the limit", () => {
    expect(fileProblem(pdf())).toBeNull();
    expect(fileProblem(new File(["x"], "a.png", { type: "image/png" }))).toBeNull();
    expect(fileProblem(new File(["x"], "a.jpg", { type: "image/jpeg" }))).toBeNull();
  });

  it("rejects empty, oversized and other files", () => {
    expect(fileProblem(new File([], "empty.pdf", { type: "application/pdf" }))).toBe("errors.file_empty");
    const big = new File([new Uint8Array(MAX_UPLOAD_BYTES + 1)], "big.pdf", { type: "application/pdf" });
    expect(fileProblem(big)).toBe("errors.file_too_large");
    expect(fileProblem(new File(["<x/>"], "a.svg", { type: "image/svg+xml" }))).toBe("errors.file_name_not_allowed");
    expect(fileProblem(new File(["x"], "doc", { type: "" }))).toBe("errors.file_type_not_allowed");
  });

  it("rejects misleading names and declared types (the server re-checks the content anyway)", () => {
    expect(fileProblem(new File(["x"], "facture.exe.pdf", { type: "application/pdf" }))).toBe(
      "errors.file_name_not_allowed",
    );
    expect(fileProblem(new File(["x"], "photo.png", { type: "application/pdf" }))).toBe("errors.file_mime_mismatch");
    expect(fileProblem(new File(["x"], "scan.JPEG", { type: "image/jpeg" }))).toBeNull();
    expect(fileProblem(new File(["x"], "scan.pdf", { type: "" }))).toBeNull();
  });
});

describe("buildRequestForm", () => {
  it("sends the JSON payload and one attachment part per document type", () => {
    const form = buildRequestForm({
      enrollmentId: "e1",
      selection: { attestation: { quantity: 2 }, convention: { quantity: 1, file: pdf() } },
      reason: "  Bourse  ",
      extraInfo: "",
    });
    expect(JSON.parse(String(form.get("payload")))).toEqual({
      enrollment_id: "e1",
      items: [
        { document_type_id: "attestation", quantity: 2 },
        { document_type_id: "convention", quantity: 1 },
      ],
      reason: "Bourse",
      extra_info: null,
    });
    expect((form.get("attachment:convention") as File).name).toBe("piece.pdf");
    expect(form.get("attachment:attestation")).toBeNull();
  });

  it("builds message bodies with files", () => {
    const form = buildMessageForm("Bonjour", [pdf(), pdf()]);
    expect(form.get("body")).toBe("Bonjour");
    expect(form.getAll("files")).toHaveLength(2);
  });
});

describe("workflow display rules", () => {
  it("mirrors the backend comment requirements", () => {
    expect(commentRequired("REJECTED")).toBe(true);
    expect(commentRequired("NEEDS_INFORMATION")).toBe(true);
    expect(commentRequired("CANCELLED")).toBe(true);
    expect(commentRequired("APPROVED")).toBe(false);
    expect(commentRequired("IN_REVIEW")).toBe(false);
  });

  it("classifies statuses", () => {
    expect(isDestructive("REJECTED")).toBe(true);
    expect(isDestructive("APPROVED")).toBe(false);
    expect(statusTone("NEEDS_INFORMATION")).toBe("warning");
    expect(statusTone("COMPLETED")).toBe("success");
    expect(statusTone("CANCELLED")).toBe("danger");
    expect(statusTone("RECEIVED")).toBe("neutral");
  });
});

describe("helpers", () => {
  it("validates request ids before calling the API", () => {
    expect(isUuid("3f2b8c1e-8a5d-4c1e-9b7a-1234567890ab")).toBe(true);
    expect(isUuid("REQ-2026-000001")).toBe(false);
    expect(isUuid("../../etc/passwd")).toBe(false);
  });

  it("reads the download filename from Content-Disposition", () => {
    const header = "attachment; filename=\"a.pdf\"; filename*=UTF-8''attestation%20%C3%A9.pdf";
    expect(dispositionFilename(header, "x")).toBe("attestation é.pdf");
    expect(dispositionFilename('attachment; filename="plain.pdf"', "x")).toBe("plain.pdf");
    expect(dispositionFilename(null, "fallback.pdf")).toBe("fallback.pdf");
  });
});
