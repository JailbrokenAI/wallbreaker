import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const require = createRequire(import.meta.url);

// build first
await import("./build.mjs");

const electronPath = require("electron");
const child = spawn(electronPath, ["."], {
  cwd: root,
  stdio: "inherit",
  env: {
    ...process.env,
    ELECTRON_DISABLE_SECURITY_WARNINGS: "true",
  },
});

child.on("exit", (code) => process.exit(code ?? 0));
