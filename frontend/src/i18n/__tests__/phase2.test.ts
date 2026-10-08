import { describe, expect, it } from "vitest";
import { REQUEST_STATUSES } from "@/lib/api/types";
import fr from "../dictionaries/fr.json";
import en from "../dictionaries/en.json";
import ar from "../dictionaries/ar.json";

function leaves(obj: object, prefix = ""): [string, string][] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? leaves(v, `${prefix}${k}.`) : [[`${prefix}${k}`, String(v)]],
  );
}

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("Phase 2 translations", () => {
  it("translate every request status and action in each locale", () => {
    for (const dict of [fr, en, ar]) {
      for (const s of REQUEST_STATUSES) {
        expect(dict.status[s]).toBeTruthy();
        expect(dict.action[s]).toBeTruthy();
      }
      for (const s of ["PENDING", "VERIFIED", "REJECTED"] as const) expect(dict.enrollmentStatus[s]).toBeTruthy();
    }
  });

  it("translate every notification type", () => {
    const types = [
      "REQUEST_RECEIVED",
      "STATUS_CHANGED",
      "INFORMATION_REQUESTED",
      "NEW_MESSAGE",
      "INFORMATION_PROVIDED",
      "REQUEST_ASSIGNED",
    ] as const;
    for (const dict of [fr, en, ar]) for (const ty of types) expect(dict.notifications[ty]).toContain("{reference}");
  });

  it("use the same placeholders in FR, EN and AR", () => {
    const enMap = new Map(leaves(en));
    const arMap = new Map(leaves(ar));
    for (const [key, value] of leaves(fr)) {
      expect(placeholders(enMap.get(key) ?? ""), key).toEqual(placeholders(value));
      expect(placeholders(arMap.get(key) ?? ""), key).toEqual(placeholders(value));
    }
  });

  it("have no empty strings and Arabic is actually Arabic for the workflow", () => {
    for (const dict of [fr, en, ar]) for (const [key, v] of leaves(dict)) expect(v.trim(), key).not.toBe("");
    for (const s of REQUEST_STATUSES) expect(ar.status[s]).toMatch(/[؀-ۿ]/);
  });
});
