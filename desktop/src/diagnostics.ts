import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { resolvePython } from "./backend";
import { projectRoot } from "./paths";
import { getSettings } from "./store";
import { isPortFree, probeUrl } from "./port";
import type { BackendStatus } from "./types";

export interface DiagnosticCheck {
  id: string;
  label: string;
  ok: boolean;
  detail: string;
}

export interface DiagnosticsReport {
  ok: boolean;
  generatedAt: string;
  checks: DiagnosticCheck[];
  summary: string;
}

function exists(p: string): boolean {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

function runPython(python: string, code: string, cwd: string, timeoutMs = 8000): Promise<{ code: number | null; out: string }> {
  return new Promise((resolve) => {
    const child = spawn(python, ["-c", code], {
      cwd,
      env: { ...process.env, PYTHONUTF8: "1" },
      windowsHide: true,
    });
    let out = "";
    const timer = setTimeout(() => {
      try {
        child.kill();
      } catch {
        /* ignore */
      }
      resolve({ code: null, out: out || "timeout" });
    }, timeoutMs);
    child.stdout.on("data", (b) => {
      out += b.toString("utf8");
    });
    child.stderr.on("data", (b) => {
      out += b.toString("utf8");
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ code: 1, out: err.message });
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      resolve({ code, out: out.trim() });
    });
  });
}

export async function runDiagnostics(backendStatus: BackendStatus): Promise<DiagnosticsReport> {
  const root = projectRoot();
  const settings = getSettings();
  const python = resolvePython(root, settings.pythonPath || undefined);
  const checks: DiagnosticCheck[] = [];

  checks.push({
    id: "project_root",
    label: "Project root",
    ok: exists(path.join(root, "wallbreaker")),
    detail: root,
  });

  checks.push({
    id: "config",
    label: "config.toml",
    ok: exists(settings.configPath || path.join(root, "config.toml")),
    detail: settings.configPath || path.join(root, "config.toml"),
  });

  const pyProbe = await runPython(python, "import sys; print(sys.version.split()[0]); print(sys.executable)", root);
  checks.push({
    id: "python",
    label: "Python interpreter",
    ok: pyProbe.code === 0,
    detail: pyProbe.code === 0 ? pyProbe.out.replace(/\n/g, " · ") : `${python} — ${pyProbe.out}`,
  });

  const modProbe = await runPython(
    python,
    "import importlib.util as u\n"
      + "mods=['wallbreaker','fastapi','uvicorn','httpx']\n"
      + "missing=[m for m in mods if u.find_spec(m) is None]\n"
      + "print('ok' if not missing else 'missing:'+','.join(missing))",
    root,
  );
  checks.push({
    id: "python_modules",
    label: "Python packages",
    ok: modProbe.code === 0 && modProbe.out.startsWith("ok"),
    detail: modProbe.out || "unknown",
  });

  const dist = path.join(root, "wallbreaker", "dashboard", "web", "dist", "index.html");
  checks.push({
    id: "dashboard_dist",
    label: "Dashboard web build",
    ok: exists(dist),
    detail: dist,
  });

  const preferred = settings.port || 8787;
  const host = settings.host || "127.0.0.1";
  const free = await isPortFree(host, preferred);
  const live = await probeUrl(`http://${host}:${preferred}/api/config`);
  checks.push({
    id: "port",
    label: `Port ${preferred}`,
    ok: free || live,
    detail: live ? "dashboard already responding" : free ? "free" : "occupied by another process",
  });

  checks.push({
    id: "backend_status",
    label: "Desktop backend manager",
    ok: backendStatus.state === "ready",
    detail:
      backendStatus.state === "ready"
        ? `${backendStatus.url}${backendStatus.owned === false ? " (external)" : ""}`
        : backendStatus.state === "error"
          ? backendStatus.message
          : backendStatus.state,
  });

  const sessions = path.join(root, "sessions");
  checks.push({
    id: "sessions",
    label: "Sessions directory",
    ok: true,
    detail: exists(sessions) ? sessions : `${sessions} (will be created)`,
  });

  const failed = checks.filter((c) => !c.ok);
  return {
    ok: failed.length === 0,
    generatedAt: new Date().toISOString(),
    checks,
    summary:
      failed.length === 0
        ? "All checks passed"
        : `${failed.length} issue(s): ${failed.map((c) => c.id).join(", ")}`,
  };
}
