import { describe, expect, it } from "vitest";
import { direction, localeFromPathname, negotiateLocale } from "../config";
import fr from "../dictionaries/fr.json";
import en from "../dictionaries/en.json";
import ar from "../dictionaries/ar.json";

describe("negotiateLocale", () => {
  it("defaults to French without header", () => {
    expect(negotiateLocale(null)).toBe("fr");
    expect(negotiateLocale("")).toBe("fr");
  });
  it("respects q-values and region subtags", () => {
    expect(negotiateLocale("de-DE,ar-MA;q=0.9,en;q=0.8")).toBe("ar");
    expect(negotiateLocale("en;q=0.5,fr;q=0.9")).toBe("fr");
  });
  it("falls back when nothing matches", () => {
    expect(negotiateLocale("de,es;q=0.8")).toBe("fr");
  });
});

describe("direction", () => {
  it("is rtl for Arabic only", () => {
    expect(direction("ar")).toBe("rtl");
    expect(direction("fr")).toBe("ltr");
    expect(direction("en")).toBe("ltr");
  });
});

describe("localeFromPathname", () => {
  it("extracts a supported prefix", () => {
    expect(localeFromPathname("/ar/admin")).toBe("ar");
    expect(localeFromPathname("/admin")).toBeNull();
    expect(localeFromPathname("/")).toBeNull();
  });
});

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? keys(v, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe("dictionaries", () => {
  it("have identical keys in every locale", () => {
    const reference = keys(fr).sort();
    expect(keys(en).sort()).toEqual(reference);
    expect(keys(ar).sort()).toEqual(reference);
  });
});
