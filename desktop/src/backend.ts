import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { EventEmitter } from "node:events";
import { projectRoot } from "./paths";
import { resolveListenPort } from "./port";
import type { BackendStatus } from "./types";

export type { BackendStatus };

export interface BackendOptions {
  host?: string;
  port?: number;
  configPath?: string;
  sessionsDir?: string;
  pythonPath?: string;
}

function exists(p: string): boolean {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

/** Prefer project venv, then PATH python. */
export function resolvePython(root: string, explicit?: string): string {
  if (explicit && exists(explicit)) return explicit;

  const win = process.platform === "win32";
  const venvCandidates = win
    ? [
        path.join(root, ".venv", "Scripts", "python.exe"),
        path.join(root, "venv", "Scripts", "python.exe"),
      ]
    : [
        path.join(root, ".venv", "bin", "python"),
        path.join(root, "venv", "bin", "python"),
      ];

  for (const c of venvCandidates) {
    if (exists(c)) return c;
  }

  return win ? "python" : "python3";
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function probe(url: string, timeoutMs = 1500): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      res.resume();
      resolve((res.statusCode ?? 500) < 500);
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

/** Consecutive health failures before treating backend as dead (avoids flapping). */
const HEALTH_FAIL_THRESHOLD = 3;
/** Health probe must tolerate a busy event loop during long agent SSE runs. */
const HEALTH_PROBE_TIMEOUT_MS = 8000;

export class BackendManager extends EventEmitter {
  private child: ChildProcessWithoutNullStreams | null = null;
  private status: BackendStatus = { state: "idle" };
  private logLines: string[] = [];
  private readonly maxLog = 500;
  private stopping = false;
  private ownedProcess = false;
  private healthTimer: NodeJS.Timeout | null = null;
  private lastOpts: BackendOptions = {};
  private reconnecting = false;
  private healthFailStreak = 0;

  getStatus(): BackendStatus {
    return this.status;
  }

  getOwned(): boolean {
    return this.ownedProcess;
  }

  getLogTail(n = 80): string {
    return this.logLines.slice(-n).join("\n");
  }

  private setStatus(next: BackendStatus): void {
    this.status = next;
    this.emit("status", next);
  }

  private pushLog(line: string): void {
    const cleaned = line.replace(/\r/g, "").trimEnd();
    if (!cleaned) return;
    this.logLines.push(cleaned);
    if (this.logLines.length > this.maxLog) {
      this.logLines.splice(0, this.logLines.length - this.maxLog);
    }
    this.emit("log", cleaned);
  }

  startHealthMonitor(autoReconnect: boolean): void {
    this.stopHealthMonitor();
    this.healthTimer = setInterval(() => {
      void this.healthTick(autoReconnect);
    }, 5000);
  }

  stopHealthMonitor(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer);
      this.healthTimer = null;
    }
  }

  private async healthTick(autoReconnect: boolean): Promise<void> {
    if (this.stopping || this.reconnecting) return;
    if (this.status.state !== "ready") return;

    // Prefer /api/health (cheap) over /api/config. Use a long timeout so a
    // saturated event loop during multi-minute agent runs does not look dead.
    // Require consecutive failures before kill/restart — a single slow tick
    // was previously restarting the backend mid-run (UI "network error").
    const base = this.status.url;
    const ok =
      (await probe(`${base}/api/health`, HEALTH_PROBE_TIMEOUT_MS)) ||
      (await probe(`${base}/api/config`, HEALTH_PROBE_TIMEOUT_MS));
    if (ok) {
      this.healthFailStreak = 0;
      return;
    }

    this.healthFailStreak += 1;
    this.pushLog(
      `[desktop] health check failed (${this.healthFailStreak}/${HEALTH_FAIL_THRESHOLD}) — backend slow or unreachable`,
    );
    if (this.healthFailStreak < HEALTH_FAIL_THRESHOLD) return;

    this.healthFailStreak = 0;
    this.pushLog("[desktop] health check exhausted — treating backend as down");
    if (autoReconnect) {
      this.reconnecting = true;
      try {
        this.pushLog("[desktop] auto-reconnect…");
        await this.restart(this.lastOpts);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        this.setStatus({ state: "error", message, logTail: this.getLogTail() });
      } finally {
        this.reconnecting = false;
      }
    } else {
      this.setStatus({
        state: "error",
        message: "Backend became unreachable",
        logTail: this.getLogTail(),
      });
    }
  }

  async start(opts: BackendOptions = {}): Promise<{ port: number; url: string }> {
    this.lastOpts = opts;
    if (this.child && this.status.state === "ready") {
      return { port: this.status.port, url: this.status.url };
    }
    if (this.child) {
      await this.stop();
    }

    const root = projectRoot();
    const host = opts.host ?? "127.0.0.1";
    const preferredPort = opts.port ?? 8787;
    const python = resolvePython(root, opts.pythonPath);
    const sessions = opts.sessionsDir ?? path.join(root, "sessions");
    const configPath =
      opts.configPath ??
      (exists(path.join(root, "config.toml")) ? path.join(root, "config.toml") : undefined);

    if (!exists(path.join(root, "wallbreaker"))) {
      const msg = `Wallbreaker project root not found at: ${root}\nSet WALLBREAKER_ROOT to your checkout.`;
      this.setStatus({ state: "error", message: msg });
      throw new Error(msg);
    }

    let port = preferredPort;
    let reused = false;
    try {
      const resolved = await resolveListenPort(host, preferredPort);
      port = resolved.port;
      reused = resolved.reused;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.setStatus({ state: "error", message });
      throw err;
    }

    if (port !== preferredPort) {
      this.pushLog(`[desktop] port ${preferredPort} busy — using ${port}`);
    }

    const url = `http://${host}:${port}`;
    if (
      reused ||
      (await probe(`${url}/api/health`, 2000)) ||
      (await probe(`${url}/api/config`, 2000))
    ) {
      this.ownedProcess = false;
      this.healthFailStreak = 0;
      this.setStatus({ state: "ready", port, url, owned: false });
      this.pushLog(`[desktop] reusing existing dashboard at ${url}`);
      return { port, url };
    }

    this.stopping = false;
    this.setStatus({ state: "starting", port, detail: `python=${python}` });
    this.pushLog(`[desktop] project root: ${root}`);
    this.pushLog(`[desktop] starting backend: ${python} -m wallbreaker dashboard --host ${host} --port ${port}`);

    const args = [
      "-m",
      "wallbreaker",
      "dashboard",
      "--host",
      host,
      "--port",
      String(port),
      "--sessions",
      sessions,
    ];
    if (configPath) {
      args.push("--config", configPath);
    }

    const child = spawn(python, args, {
      cwd: root,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
        PYTHONUTF8: "1",
      },
      windowsHide: true,
    });
    this.child = child;
    this.ownedProcess = true;

    child.stdout.on("data", (buf: Buffer) => {
      for (const line of buf.toString("utf8").split("\n")) this.pushLog(line);
    });
    child.stderr.on("data", (buf: Buffer) => {
      for (const line of buf.toString("utf8").split("\n")) this.pushLog(line);
    });
    child.on("error", (err) => {
      this.pushLog(`[desktop] spawn error: ${err.message}`);
      this.setStatus({
        state: "error",
        message: `Failed to start Python backend: ${err.message}`,
        logTail: this.getLogTail(),
      });
    });
    child.on("exit", (code, signal) => {
      this.child = null;
      if (this.stopping) {
        this.setStatus({ state: "idle" });
        return;
      }
      const msg = `Backend exited (code=${code ?? "null"} signal=${signal ?? "null"})`;
      this.pushLog(`[desktop] ${msg}`);
      if (this.status.state !== "error") {
        this.setStatus({ state: "error", message: msg, logTail: this.getLogTail() });
      }
    });

    const deadline = Date.now() + 60_000;
    while (Date.now() < deadline) {
      if (!this.child) {
        throw new Error(this.status.state === "error" ? this.status.message : "Backend process died");
      }
      if (
        (await probe(`${url}/api/health`, 2000)) ||
        (await probe(`${url}/api/config`, 2000))
      ) {
        this.healthFailStreak = 0;
        this.setStatus({ state: "ready", port, url, owned: true });
        this.pushLog(`[desktop] backend ready at ${url}`);
        return { port, url };
      }
      if (await probe(url, 1500)) {
        if (
          (await probe(`${url}/api/health`, 2000)) ||
          (await probe(`${url}/api/config`, 2000))
        ) {
          this.healthFailStreak = 0;
          this.setStatus({ state: "ready", port, url, owned: true });
          this.pushLog(`[desktop] backend ready at ${url}`);
          return { port, url };
        }
      }
      await sleep(400);
    }

    const timeoutMsg =
      "Timed out waiting for dashboard backend. Install deps: pip install -e \".[dashboard]\" and build web UI.";
    this.setStatus({ state: "error", message: timeoutMsg, logTail: this.getLogTail() });
    await this.stop();
    throw new Error(timeoutMsg);
  }

  async stop(): Promise<void> {
    this.stopping = true;
    const child = this.child;
    this.child = null;
    if (!child || child.killed) {
      this.ownedProcess = false;
      this.setStatus({ state: "idle" });
      return;
    }

    this.pushLog("[desktop] stopping backend…");
    try {
      if (process.platform === "win32") {
        spawn("taskkill", ["/pid", String(child.pid), "/f", "/t"], { windowsHide: true });
      } else {
        child.kill("SIGTERM");
      }
    } catch {
      /* ignore */
    }

    const waitUntil = Date.now() + 4000;
    while (Date.now() < waitUntil && !child.killed) {
      await sleep(100);
    }
    try {
      child.kill("SIGKILL");
    } catch {
      /* ignore */
    }
    this.ownedProcess = false;
    this.setStatus({ state: "idle" });
  }

  async restart(opts: BackendOptions = {}): Promise<{ port: number; url: string }> {
    // Only kill process we own; external servers are left alone and re-probed.
    if (this.ownedProcess) {
      await this.stop();
    } else {
      this.child = null;
      this.setStatus({ state: "idle" });
    }
    return this.start({ ...this.lastOpts, ...opts });
  }
}
