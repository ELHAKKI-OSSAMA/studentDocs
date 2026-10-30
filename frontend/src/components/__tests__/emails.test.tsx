// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import { ConfidenceBadge, EmailStatusBadge, SandboxedHtml } from "@/components/emails";
import { EMAIL_CASE_STATUSES, REVIEW_CONFIDENCES } from "@/lib/api/types";
import { renderWithProviders } from "@/test/render";
import fr from "@/i18n/dictionaries/fr.json";
import en from "@/i18n/dictionaries/en.json";
import ar from "@/i18n/dictionaries/ar.json";

afterEach(cleanup);

describe("email review components", () => {
  it("renders sanitized HTML only inside a fully sandboxed frame that cannot load anything", () => {
    renderWithProviders(<SandboxedHtml html="<p>Bonjour</p>" title="email" />);
    const frame = screen.getByTestId("email-html-frame");
    expect(frame.tagName).toBe("IFRAME");
    // Empty sandbox: no scripts, no forms, no popups, no top navigation, opaque origin.
    expect(frame.getAttribute("sandbox")).toBe("");
    const doc = frame.getAttribute("srcdoc") ?? "";
    expect(doc).toContain("default-src 'none'");
    expect(doc).toContain("<p>Bonjour</p>");
  });

  it("never presents the review confidence as an authorization", () => {
    for (const level of REVIEW_CONFIDENCES) {
      renderWithProviders(<ConfidenceBadge level={level} />);
      const badge = screen.getByTestId("review-confidence");
      expect(badge.getAttribute("title")).toContain("ne déclenche aucune action");
      cleanup();
    }
  });

  it("labels every email status in FR, EN and AR (no raw key), in RTL for Arabic", () => {
    for (const status of EMAIL_CASE_STATUSES) {
      for (const dict of [fr, en, ar]) expect(dict.emailStatus[status]).toBeTruthy();
      expect(ar.emailStatus[status]).toMatch(/[؀-ۿ]/);
    }
    renderWithProviders(<EmailStatusBadge status="NEEDS_REVIEW" />, "ar");
    expect(screen.getByTestId("email-status").textContent).toBe(ar.emailStatus.NEEDS_REVIEW);
    expect(screen.getByTestId("root").getAttribute("dir")).toBe("rtl");
  });

  it("translates the review vocabulary in every locale", () => {
    for (const dict of [fr, en, ar]) {
      for (const level of REVIEW_CONFIDENCES) expect(dict.reviewConfidence[level]).toBeTruthy();
      expect(dict.requests.kindEMAIL_ATTACHMENT).toBeTruthy();
      expect(Object.keys(dict.emails).length).toBe(Object.keys(fr.emails).length);
    }
  });
});
