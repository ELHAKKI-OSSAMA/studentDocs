// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { RequestActions } from "@/components/request-actions";
import { StatusBadge, Timeline } from "@/components/requests";
import type { RequestDetail } from "@/lib/api/types";
import { renderWithProviders, stubFetch, type Route } from "@/test/render";

const ID = "3f2b8c1e-8a5d-4c1e-9b7a-1234567890ab";

function request(overrides: Partial<RequestDetail> = {}): RequestDetail {
  return {
    id: ID,
    reference: "REQ-2026-000001",
    status: "PROCESSING",
    available_transitions: ["APPROVED", "REJECTED", "CANCELLED"],
    history: [],
    ...overrides,
  } as RequestDetail;
}

function setup(routes: Route[] = []) {
  const { fetchMock, calls } = stubFetch(routes);
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

beforeEach(() => {
  document.cookie = "sd_csrf=csrf-token-value";
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("RequestActions", () => {
  it("offers exactly the transitions computed by the backend", () => {
    setup();
    renderWithProviders(<RequestActions request={request()} />);
    const buttons = within(screen.getByTestId("transition-buttons")).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Approuver", "Refuser", "Annuler la demande"]);
    expect(screen.queryByText("Clôturer")).toBeNull();
  });

  it("shows no action when the user may not act (e.g. missing permission)", () => {
    setup();
    renderWithProviders(<RequestActions request={request({ available_transitions: [] })} />);
    expect(screen.queryByTestId("transition-buttons")).toBeNull();
    expect(screen.getByText("Aucune action disponible dans cet état.")).toBeTruthy();
  });

  it("requires a reason to reject and does not call the API without one", async () => {
    const calls = setup();
    renderWithProviders(<RequestActions request={request()} />);
    fireEvent.click(screen.getByTestId("transition-REJECTED"));
    fireEvent.click(await screen.findByTestId("confirm-transition"));
    expect((await screen.findByTestId("transition-error")).textContent).toBe("Un message est obligatoire.");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("posts the transition with the CSRF header", async () => {
    const calls = setup([{ method: "POST", path: `/api/v1/admin/requests/${ID}/transitions`, body: request() }]);
    renderWithProviders(<RequestActions request={request()} />);
    fireEvent.click(screen.getByTestId("transition-APPROVED"));
    fireEvent.click(await screen.findByTestId("confirm-transition"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    const post = calls.find((c) => c.method === "POST")!;
    expect(JSON.parse(String(post.init.body))).toEqual({ to_status: "APPROVED", comment: null });
    expect((post.init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-token-value");
  });

  it("translates API refusals instead of showing raw server text", async () => {
    setup([
      {
        method: "POST",
        path: `/api/v1/admin/requests/${ID}/transitions`,
        status: 409,
        body: { error: { code: "transition_not_allowed", message: "Transition not allowed (raw)" } },
      },
    ]);
    renderWithProviders(<RequestActions request={request()} />);
    fireEvent.click(screen.getByTestId("transition-APPROVED"));
    fireEvent.click(await screen.findByTestId("confirm-transition"));
    expect((await screen.findByTestId("transition-error")).textContent).toBe(
      "Cette action n'est pas possible dans l'état actuel de la demande.",
    );
  });

  it("is translated in English and Arabic", () => {
    setup();
    renderWithProviders(<RequestActions request={request()} />, "en");
    expect(screen.getByTestId("transition-APPROVED").textContent).toBe("Approve");
    cleanup();
    renderWithProviders(<RequestActions request={request()} />, "ar");
    expect(screen.getByTestId("transition-APPROVED").textContent).toBe("قبول");
    expect(screen.getByTestId("root").getAttribute("dir")).toBe("rtl");
  });
});

describe("status display", () => {
  it("renders localized status badges and the timeline", () => {
    renderWithProviders(
      <Timeline
        history={[
          { from_status: null, to_status: "SUBMITTED", actor_role: "STUDENT", comment: null, created_at: "2026-10-01T10:00:00Z" },
          { from_status: "SUBMITTED", to_status: "RECEIVED", actor_role: "SYSTEM", comment: null, created_at: "2026-10-01T10:00:01Z" },
          { from_status: "RECEIVED", to_status: "IN_REVIEW", actor_role: "ADMIN", comment: "Vu", created_at: "2026-10-02T09:00:00Z" },
        ]}
      />,
      "ar",
    );
    const badges = screen.getAllByTestId("request-status").map((b) => b.textContent);
    expect(badges).toEqual(["مُرسلة", "مستلمة", "قيد الدراسة"]);
    expect(screen.getByText("Vu")).toBeTruthy();
    expect(screen.getAllByText(/الإدارة/).length).toBe(1);
  });

  it("never shows a raw translation key", () => {
    renderWithProviders(<StatusBadge status="NEEDS_INFORMATION" />, "en");
    expect(screen.getByTestId("request-status").textContent).toBe("Information needed");
  });
});
