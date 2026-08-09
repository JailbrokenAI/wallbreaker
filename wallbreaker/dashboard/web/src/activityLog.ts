export type ActivityLevel = "debug" | "info" | "tool" | "ok" | "warn" | "error" | "system";
export type ActivitySource = "agent" | "console" | "backend" | "system" | "desktop";

export interface ActivityLine {
  id: number;
  ts: number;
  source: ActivitySource;
  level: ActivityLevel;
  text: string;
  meta?: Record<string, unknown>;
}

type Listener = (line: ActivityLine) => void;

const MAX = 2000;
const lines: ActivityLine[] = [];
const listeners = new Set<Listener>();
let seq = 1;

export function appendActivity(
  source: ActivitySource,
  text: string,
  level: ActivityLevel = "info",
  meta?: Record<string, unknown>,
): ActivityLine {
  const line: ActivityLine = {
    id: seq++,
    ts: Date.now(),
    source,
    level,
    text: String(text ?? "").replace(/\r/g, ""),
    meta,
  };
  lines.push(line);
  if (lines.length > MAX) lines.splice(0, lines.length - MAX);
  listeners.forEach((fn) => {
    try {
      fn(line);
    } catch {
      /* ignore */
    }
  });
  return line;
}

export function getActivity(n = 500): ActivityLine[] {
  return lines.slice(-n);
}

export function clearActivity(): void {
  lines.length = 0;
  appendActivity("system", "— 日志已清空 —", "system");
}

export function subscribeActivity(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Format agent SSE-ish events into terminal lines. */
export function activityFromAgentEvent(ev: {
  type: string;
  [k: string]: unknown;
}): void {
  switch (ev.type) {
    case "start":
      appendActivity(
        "agent",
        `▶ run start  brain=${ev.brain || "?"}  target=${ev.target || "?"}`,
        "system",
        { event: ev.type },
      );
      break;
    case "round":
      appendActivity("agent", `── round ${ev.round}/${ev.max} ──`, "debug", { event: ev.type });
      break;
    case "text": {
      const t = String(ev.text || "");
      if (t.trim()) appendActivity("agent", t, "info", { event: ev.type });
      break;
    }
    case "tool_start":
      appendActivity(
        "agent",
        `⚙ ${ev.name}(${String(ev.args || "").slice(0, 240)})`,
        "tool",
        { event: ev.type, name: ev.name },
      );
      break;
    case "tool_result": {
      const verdict = String(ev.verdict || "").toUpperCase();
      const level: ActivityLevel =
        verdict === "COMPLIED" ? "ok" : verdict === "PARTIAL" ? "warn" : ev.error ? "error" : "tool";
      const head = verdict ? `[${verdict}] ` : ev.error ? "[ERR] " : "";
      const body = String(ev.content || "").slice(0, 800);
      appendActivity("agent", `↳ ${ev.name} ${head}${body}`, level, {
        event: ev.type,
        name: ev.name,
        verdict,
      });
      break;
    }
    case "progress":
      appendActivity("agent", `… ${ev.text}`, "debug", { event: ev.type });
      break;
    case "feedback":
    case "steer_queued":
    case "control":
      appendActivity("agent", `◎ ${ev.text || ev.message || ev.state || ev.type}`, "system", {
        event: ev.type,
      });
      break;
    case "done":
      appendActivity(
        "agent",
        `■ done  status=${ev.status}  ${String(ev.summary || "").slice(0, 200)}`,
        String(ev.status) === "finished" ? "ok" : "warn",
        { event: ev.type, status: ev.status },
      );
      break;
    case "error":
      appendActivity("agent", `✖ ${ev.error}`, "error", { event: ev.type });
      break;
    default:
      break;
  }
}
