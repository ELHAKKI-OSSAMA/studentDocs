// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, screen, within } from "@testing-library/react";
import { DocumentList, hasPendingScan } from "@/components/requests";
import type { RequestDocument, ScanStatus } from "@/lib/api/types";
import { renderWithProviders } from "@/test/render";

function doc(id: string, scan_status: ScanStatus, extra: Partial<RequestDocument> = {}): RequestDocument {
  return {
    id,
    kind: "ATTACHMENT",
    filename: `${id}.pdf`,
    mime_type: "application/pdf",
    size_bytes: 2048,
    sha256: "a".repeat(64),
    scan_status,
    scan_reason: null,
    scanned_at: null,
    can_download: scan_status === "CLEAN",
    request_item_id: null,
    message_id: null,
    created_at: "2026-10-08T10:00:00Z",
    original_filename: null,
    scan_detail: null,
    ...extra,
  };
}

const DOCS = [
  doc("clean", "CLEAN"),
  doc("pending", "SCANNING"),
  doc("infected", "INFECTED", { scan_reason: "virus_detected" }),
  doc("failed", "ERROR", { scan_reason: "scanner_unavailable" }),
  doc("legacy", "NOT_SCANNED"),
];

function row(id: string) {
  return screen.getAllByTestId("document-row").find((r) => r.textContent?.includes(`${id}.pdf`))!;
}

afterEach(cleanup);

describe("DocumentList", () => {
  it("offers a download only for files scanned CLEAN", () => {
    renderWithProviders(<DocumentList basePath="/requests/r1" documents={DOCS} />);
    expect(within(row("clean")).queryByTestId("download-document")).not.toBeNull();
    for (const id of ["pending", "infected", "failed", "legacy"]) {
      expect(within(row(id)).queryByTestId("download-document")).toBeNull();
    }
  });

  it("never presents a file as accepted before the scan", () => {
    renderWithProviders(<DocumentList basePath="/requests/r1" documents={DOCS} />);
    const status = (id: string) => within(row(id)).getByTestId("scan-status").textContent;
    expect(status("clean")).toBe("Accepté");
    expect(status("pending")).toBe("Analyse antivirus en cours");
    expect(status("infected")).toBe("Rejeté : menace détectée");
    expect(status("failed")).toBe("Erreur d'analyse");
    expect(within(row("pending")).getByTestId("scan-explanation").textContent).toContain("Fichier reçu");
    expect(within(row("infected")).getByTestId("scan-explanation").textContent).toContain("ne sera jamais transmis");
  });

  it("shows the scanner detail to staff only", () => {
    const infected = doc("infected", "INFECTED", {
      scan_detail: "virus_detected:Eicar-Test-Signature",
      original_filename: "attestation.pdf",
    });
    renderWithProviders(<DocumentList basePath="/admin/requests/r1" documents={[infected]} staff />);
    expect(screen.getByTestId("scan-detail").textContent).toContain("Eicar-Test-Signature");
    cleanup();
    renderWithProviders(<DocumentList basePath="/requests/r1" documents={[{ ...infected, scan_detail: null }]} />);
    expect(screen.queryByTestId("scan-detail")).toBeNull();
  });

  it("is translated in Arabic (RTL)", () => {
    renderWithProviders(<DocumentList basePath="/requests/r1" documents={DOCS} />, "ar");
    expect(within(row("pending")).getByTestId("scan-status").textContent).toBe("الفحص بمضاد الفيروسات جارٍ");
    expect(screen.getByTestId("root").getAttribute("dir")).toBe("rtl");
  });

  it("knows when to poll", () => {
    expect(hasPendingScan(DOCS)).toBe(true);
    expect(hasPendingScan([doc("x", "CLEAN"), doc("y", "INFECTED")])).toBe(false);
    expect(hasPendingScan(undefined)).toBe(false);
  });
});
