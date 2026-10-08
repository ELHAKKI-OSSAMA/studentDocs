import { describe, expect, it } from "vitest";
import { resolveRedirect, safeNext } from "../routing";

describe("resolveRedirect", () => {
  it("adds a locale prefix, preferring the persisted cookie over Accept-Language", () => {
    expect(resolveRedirect({ pathname: "/", acceptLanguage: "en" })).toBe("/en");
    expect(resolveRedirect({ pathname: "/", acceptLanguage: "en", localeCookie: "ar" })).toBe("/ar");
    expect(resolveRedirect({ pathname: "/student", search: "?a=1", localeCookie: "bogus" })).toBe(
      "/fr/student?a=1",
    );
  });

  it("sends anonymous visitors of protected areas to login with a return path", () => {
    expect(resolveRedirect({ pathname: "/fr/admin/users" })).toBe("/fr/login?next=%2Ffr%2Fadmin%2Fusers");
    expect(resolveRedirect({ pathname: "/ar/student" })).toBe("/ar/login?next=%2Far%2Fstudent");
  });

  it("keeps each role in its area and skips guest pages when signed in", () => {
    expect(resolveRedirect({ pathname: "/fr/admin", sessionArea: "student" })).toBe("/fr/student");
    expect(resolveRedirect({ pathname: "/en/student", sessionArea: "admin" })).toBe("/en/admin");
    expect(resolveRedirect({ pathname: "/fr/login", sessionArea: "admin" })).toBe("/fr/admin");
    expect(resolveRedirect({ pathname: "/fr/admin", sessionArea: "admin" })).toBeNull();
    expect(resolveRedirect({ pathname: "/fr/login" })).toBeNull();
    expect(resolveRedirect({ pathname: "/fr/verify-email", sessionArea: "student" })).toBeNull();
  });
});

describe("safeNext", () => {
  it("rejects open redirects", () => {
    expect(safeNext("https://evil.example", "fr", "/fr/student")).toBe("/fr/student");
    expect(safeNext("//evil.example", "fr", "/fr/student")).toBe("/fr/student");
    expect(safeNext("/\\evil.example", "fr", "/fr/student")).toBe("/fr/student");
    expect(safeNext(null, "fr", "/fr/student")).toBe("/fr/student");
  });
  it("accepts in-app paths", () => {
    expect(safeNext("/ar/admin/users", "fr", "/fr/admin")).toBe("/ar/admin/users");
    expect(safeNext("/admin", "en", "/en/admin")).toBe("/en/admin");
  });
});
