import * as esbuild from "esbuild";
import { mkdirSync, cpSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const dist = path.join(root, "dist");

mkdirSync(dist, { recursive: true });

await esbuild.build({
  entryPoints: {
    main: path.join(root, "src/main.ts"),
    preload: path.join(root, "src/preload.ts"),
  },
  outdir: dist,
  bundle: true,
  platform: "node",
  target: "node20",
  format: "cjs",
  external: ["electron", "electron-store"],
  sourcemap: true,
  logLevel: "info",
});

// electron-store is CJS-friendly; keep node_modules resolution at runtime
console.log("[desktop] build ok ->", dist);
