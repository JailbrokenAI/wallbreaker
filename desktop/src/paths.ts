import fs from "node:fs";
import path from "node:path";
import { app } from "electron";

/** Absolute path to the Wallbreaker repo root (parent of desktop/). */
export function projectRoot(): string {
  // dev: desktop/dist -> ../../  | packaged: still prefer env override
  const fromEnv = process.env.WALLBREAKER_ROOT;
  if (fromEnv && fs.existsSync(fromEnv)) return path.resolve(fromEnv);

  if (app.isPackaged) {
    // Installer users should set WALLBREAKER_ROOT or keep source checkout.
    const candidate = path.resolve(process.resourcesPath, "..", "wallbreaker-src");
    if (fs.existsSync(candidate)) return candidate;
  }

  // desktop/dist/main.js -> desktop -> repo root
  return path.resolve(__dirname, "..", "..");
}

export function splashPath(): string {
  const packaged = path.join(process.resourcesPath, "splash.html");
  if (app.isPackaged && fs.existsSync(packaged)) return packaged;
  return path.join(__dirname, "..", "resources", "splash.html");
}

export function iconPath(): string | undefined {
  const candidates = [
    path.join(process.resourcesPath || "", "icon.png"),
    path.join(__dirname, "..", "resources", "icon.png"),
    path.join(projectRoot(), "desktop", "resources", "icon.png"),
  ];
  return candidates.find((p) => p && fs.existsSync(p));
}
