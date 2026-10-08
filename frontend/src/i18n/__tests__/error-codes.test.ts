import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import fr from "../dictionaries/fr.json";
import en from "../dictionaries/en.json";
import ar from "../dictionaries/ar.json";

const BACKEND_APP = join(__dirname, "../../../../backend/app");

function pyFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? pyFiles(path) : path.endsWith(".py") ? [path] : [];
  });
}

/** Error codes raised by the API: `.of(<status>, "<code>"` and `code = "<code>"` class attributes. */
function backendErrorCodes(): Set<string> {
  const codes = new Set<string>();
  for (const file of pyFiles(BACKEND_APP)) {
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(/\.of\(\s*\d{3},\s*"([a-z_]+)"/g)) codes.add(m[1]);
    for (const m of src.matchAll(/^\s+code = "([a-z_]+)"/gm)) codes.add(m[1]);
    for (const m of src.matchAll(/"code": "([a-z_]+)"/g)) codes.add(m[1]);
  }
  return codes;
}

describe.skipIf(!existsSync(BACKEND_APP))("API error codes", () => {
  it("every backend error code is translated in FR, EN and AR", () => {
    const codes = backendErrorCodes();
    expect(codes.size).toBeGreaterThan(10);
    for (const dict of [fr, en, ar]) {
      const missing = [...codes].filter((c) => !(c in dict.errors));
      expect(missing).toEqual([]);
    }
  });
});
