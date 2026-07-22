import { describe, it, expect } from "vitest";
import { ELLIPSIS, emptyPlaceholder, formatTimestamp, snippet } from "../format";

describe("format (VIS-4) — shared formatting util", () => {
  describe("emptyPlaceholder", () => {
    it("is the single canonical em-dash placeholder", () => {
      expect(emptyPlaceholder).toBe("—");
    });
  });

  describe("ELLIPSIS", () => {
    it("is the single-character ellipsis, not three dots", () => {
      expect(ELLIPSIS).toBe("…");
      expect(ELLIPSIS).not.toBe("...");
      expect(ELLIPSIS.length).toBe(1);
    });
  });

  describe("formatTimestamp", () => {
    it("returns the placeholder for empty/nullish input", () => {
      expect(formatTimestamp("")).toBe(emptyPlaceholder);
      expect(formatTimestamp(null)).toBe(emptyPlaceholder);
      expect(formatTimestamp(undefined)).toBe(emptyPlaceholder);
    });

    it("parses a run-log filename (dash form)", () => {
      expect(formatTimestamp("run-20260707-011219.jsonl")).toBe("2026-07-07 01:12:19");
    });

    it("parses a run-log filename (no inner dash)", () => {
      expect(formatTimestamp("run-20260101120000.jsonl")).toBe("2026-01-01 12:00:00");
    });

    it("returns the placeholder for a run-log filename with an invalid clock", () => {
      // month 13 / hour 25 are out of range.
      expect(formatTimestamp("run-20261301-250000.jsonl")).toBe(emptyPlaceholder);
    });

    it("formats an epoch-seconds number", () => {
      // 2026-07-07T01:12:19Z rendered in the host local zone; assert the shape.
      const out = formatTimestamp(1783386739);
      expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    });

    it("formats an ISO string", () => {
      const out = formatTimestamp("2026-07-07T01:12:19Z");
      expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
    });

    it("returns the trimmed original when it cannot parse a non-empty string", () => {
      expect(formatTimestamp("  not-a-date  ")).toBe("not-a-date");
    });
  });

  describe("snippet", () => {
    it("returns the placeholder for empty input", () => {
      expect(snippet("")).toBe(emptyPlaceholder);
      expect(snippet("   ")).toBe(emptyPlaceholder);
      expect(snippet(null)).toBe(emptyPlaceholder);
    });

    it("collapses whitespace", () => {
      expect(snippet("a\n  b\t c")).toBe("a b c");
    });

    it("does not truncate text under the limit", () => {
      expect(snippet("short", 100)).toBe("short");
    });

    it("truncates with the single ellipsis when over the limit", () => {
      const out = snippet("abcdefghij", 4);
      expect(out).toBe(`abcd${ELLIPSIS}`);
      expect(out.endsWith("…")).toBe(true);
      expect(out.includes("...")).toBe(false);
    });

    it("stringifies non-string values before truncating", () => {
      expect(snippet(12345, 3)).toBe(`123${ELLIPSIS}`);
    });
  });
});
