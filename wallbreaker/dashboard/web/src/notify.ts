import { desktop, isDesktop } from "./desktop";

const recent = new Map<string, number>();
const COOLDOWN_MS = 4000;

function allow(key: string): boolean {
  const now = Date.now();
  const last = recent.get(key) ?? 0;
  if (now - last < COOLDOWN_MS) return false;
  recent.set(key, now);
  // prune
  if (recent.size > 50) {
    for (const [k, t] of recent) {
      if (now - t > 60_000) recent.delete(k);
    }
  }
  return true;
}

export async function notifyComplied(opts: {
  technique?: string;
  source?: string;
  detail?: string;
}): Promise<void> {
  if (!isDesktop()) return;
  const api = desktop();
  if (!api) return;

  try {
    const settings = await api.getSettings();
    if (settings.notifyOnComply === false) return;
  } catch {
    /* default on */
  }

  const technique = (opts.technique || "attack").trim() || "attack";
  const source = opts.source || "agent";
  const key = `${source}:${technique}`;
  if (!allow(key)) return;

  const title = "Daedalus · COMPLIED";
  const body = [
    technique !== "attack" ? `Technique: ${technique}` : null,
    opts.detail ? opts.detail.slice(0, 160) : null,
    `Source: ${source}`,
  ]
    .filter(Boolean)
    .join("\n");

  try {
    await api.notify(title, body || "Bypass detected");
  } catch {
    /* ignore */
  }
}

export function maybeNotifyVerdict(
  verdict: string | undefined,
  opts: { technique?: string; source?: string; detail?: string },
): void {
  if ((verdict || "").toUpperCase() === "COMPLIED") {
    void notifyComplied(opts);
  }
}
