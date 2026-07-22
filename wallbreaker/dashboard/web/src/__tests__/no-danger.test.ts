import { describe, it, expect } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(entry)) out.push(full);
  }
  return out;
}

// INFO-1: regression guard — no raw HTML injection anywhere in the SPA source.
describe("XSS regression guard (INFO-1)", () => {
  const files = walk(SRC).filter((f) => !f.includes("__tests__"));

  it("finds no dangerouslySetInnerHTML in src/**", () => {
    const offenders = files.filter((f) => readFileSync(f, "utf8").includes("dangerouslySetInnerHTML"));
    expect(offenders, `dangerouslySetInnerHTML found in:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("finds no direct .innerHTML assignment in src/**", () => {
    const offenders = files.filter((f) => /\.innerHTML\s*=/.test(readFileSync(f, "utf8")));
    expect(offenders, `.innerHTML = found in:\n${offenders.join("\n")}`).toEqual([]);
  });
});
