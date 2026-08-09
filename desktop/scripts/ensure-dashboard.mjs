/**
 * Ensure the React dashboard is built before packaging / first run.
 * Invoked optionally from package scripts.
 */
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(__dirname, "..", "..");
const web = path.join(repo, "wallbreaker", "dashboard", "web");
const distIndex = path.join(web, "dist", "index.html");

if (existsSync(distIndex)) {
  console.log("[desktop] dashboard dist present");
  process.exit(0);
}

console.log("[desktop] building dashboard web…");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
let r = spawnSync(npm, ["install"], { cwd: web, stdio: "inherit", shell: true });
if (r.status !== 0) process.exit(r.status ?? 1);
r = spawnSync(npm, ["run", "build"], { cwd: web, stdio: "inherit", shell: true });
process.exit(r.status ?? 1);
