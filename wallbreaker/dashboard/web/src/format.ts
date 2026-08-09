// VIS-4: one shared formatting module so timestamps, truncation ellipses, and
// the "empty" placeholder render identically everywhere. Previously Runs had
// `timeFromRunName`, Findings printed the raw `ts`, snippets mixed "..." and
// "…", and five different empty strings ("—"/"-"/"not recorded"/"not set"/
// "Not set") diverged across components.

/** The single canonical ellipsis character used for all truncation. */
export const ELLIPSIS = "…";

/** One canonical placeholder for "not set"/"none"/"not recorded"/"—". */
export const emptyPlaceholder = "—";

/**
 * Format a timestamp for display. Accepts either an ISO-ish timestamp string,
 * an epoch number, or a `run-YYYYMMDD-HHMMSS.jsonl` run-log filename. Returns a
 * stable `YYYY-MM-DD HH:MM:SS` string, or `emptyPlaceholder` when it can't be
 * parsed (so callers never print a raw/garbled value).
 */
export function formatTimestamp(ts: string | number | null | undefined): string {
  if (ts == null || ts === "") return emptyPlaceholder;

  if (typeof ts === "string") {
    // run-log filename form: run-YYYYMMDD-HHMMSS.jsonl (dash optional).
    const runMatch = /^run-(\d{8})-?(\d{6})\.jsonl$/.exec(ts);
    if (runMatch) {
      const stamp = `${runMatch[1]}${runMatch[2]}`;
      const year = stamp.slice(0, 4);
      const month = Number(stamp.slice(4, 6));
      const day = Number(stamp.slice(6, 8));
      const hour = Number(stamp.slice(8, 10));
      const minute = Number(stamp.slice(10, 12));
      const second = Number(stamp.slice(12, 14));
      const valid =
        month >= 1 && month <= 12 &&
        day >= 1 && day <= 31 &&
        hour <= 23 && minute <= 59 && second <= 59;
      if (!valid) return emptyPlaceholder;
      return `${year}-${stamp.slice(4, 6)}-${stamp.slice(6, 8)} ${stamp.slice(8, 10)}:${stamp.slice(10, 12)}:${stamp.slice(12, 14)}`;
    }
  }

  // Numeric epoch (seconds or milliseconds) or a Date-parseable string.
  const asNumber = typeof ts === "number" ? ts : Number(ts);
  let date: Date | null = null;
  if (typeof ts === "number" || (typeof ts === "string" && ts.trim() !== "" && !Number.isNaN(asNumber) && /^\d+(\.\d+)?$/.test(ts.trim()))) {
    // Heuristic: values below ~10^12 are seconds, otherwise milliseconds.
    const ms = asNumber < 1e12 ? asNumber * 1000 : asNumber;
    const d = new Date(ms);
    if (!Number.isNaN(d.getTime())) date = d;
  } else if (typeof ts === "string") {
    const d = new Date(ts);
    if (!Number.isNaN(d.getTime())) date = d;
  }

  if (!date) {
    // Not parseable but non-empty — show the trimmed original rather than losing it.
    return typeof ts === "string" && ts.trim() ? ts.trim() : emptyPlaceholder;
  }

  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

/**
 * Collapse whitespace and truncate `text` to at most `n` characters, appending
 * the single canonical ELLIPSIS when truncated. Returns `emptyPlaceholder` for
 * empty input so callers get a consistent "nothing here" string.
 */
export function snippet(text: unknown, n = 180): string {
  const compact = toText(text).replace(/\s+/g, " ").trim();
  if (!compact) return emptyPlaceholder;
  return compact.length > n ? `${compact.slice(0, n)}${ELLIPSIS}` : compact;
}

function toText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
