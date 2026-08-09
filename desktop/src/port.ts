import net from "node:net";
import http from "node:http";

export function isPortFree(host: string, port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.once("listening", () => {
      server.close(() => resolve(true));
    });
    server.listen(port, host);
  });
}

export function probeUrl(url: string, timeoutMs = 1200): Promise<boolean> {
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

async function isOurDashboard(url: string): Promise<boolean> {
  // Accept either health or config — health is cheaper and always present.
  return (
    (await probeUrl(`${url}/api/health`, 2000)) ||
    (await probeUrl(`${url}/api/config`, 2000))
  );
}

/** Prefer preferredPort; if occupied by our dashboard, reuse; else scan upward. */
export async function resolveListenPort(
  host: string,
  preferredPort: number,
  maxTries = 20,
): Promise<{ port: number; reused: boolean }> {
  const preferredUrl = `http://${host}:${preferredPort}`;
  if (await isOurDashboard(preferredUrl)) {
    return { port: preferredPort, reused: true };
  }
  if (await isPortFree(host, preferredPort)) {
    return { port: preferredPort, reused: false };
  }
  for (let i = 1; i <= maxTries; i++) {
    const candidate = preferredPort + i;
    if (candidate > 65535) break;
    const url = `http://${host}:${candidate}`;
    if (await isOurDashboard(url)) {
      return { port: candidate, reused: true };
    }
    if (await isPortFree(host, candidate)) {
      return { port: candidate, reused: false };
    }
  }
  throw new Error(
    `No free port near ${preferredPort} (tried ${maxTries} alternatives). Close other services or change the desktop port setting.`,
  );
}
