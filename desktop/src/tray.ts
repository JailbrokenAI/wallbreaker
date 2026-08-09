import { BrowserWindow, Menu, Tray, nativeImage } from "electron";
import { iconPath } from "./paths";
import type { BackendStatus } from "./types";

function makeFallbackIcon(): Electron.NativeImage {
  const size = 16;
  const buf = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = Math.abs(x - 7.5);
      const dy = Math.abs(y - 7.5);
      const inside = dx + dy < 7;
      const i = (y * size + x) * 4;
      buf[i] = inside ? 255 : 0;
      buf[i + 1] = inside ? 59 : 0;
      buf[i + 2] = inside ? 71 : 0;
      buf[i + 3] = inside ? 255 : 0;
    }
  }
  return nativeImage.createFromBuffer(buf, { width: size, height: size });
}

function tintForStatus(status: BackendStatus): { r: number; g: number; b: number } {
  switch (status.state) {
    case "ready":
      return { r: 45, g: 226, b: 200 }; // accent
    case "starting":
      return { r: 232, g: 163, b: 61 }; // warn
    case "error":
      return { r: 255, g: 59, b: 71 }; // brand
    default:
      return { r: 160, g: 116, b: 120 }; // muted
  }
}

function buildStatusIcon(status: BackendStatus): Electron.NativeImage {
  const file = iconPath();
  let base = file ? nativeImage.createFromPath(file) : nativeImage.createEmpty();
  if (base.isEmpty()) base = makeFallbackIcon();
  else base = base.resize({ width: 16, height: 16 });

  // Overlay a status dot in the corner
  const size = 16;
  const png = base.toBitmap();
  // toBitmap may not be ideal for all formats; redraw simple diamond + dot instead
  const color = tintForStatus(status);
  const buf = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = Math.abs(x - 7.5);
      const dy = Math.abs(y - 7.5);
      const inside = dx + dy < 6.5;
      const i = (y * size + x) * 4;
      const isDot = x >= 11 && y >= 11 && x <= 14 && y <= 14;
      if (isDot) {
        buf[i] = color.r;
        buf[i + 1] = color.g;
        buf[i + 2] = color.b;
        buf[i + 3] = 255;
      } else if (inside) {
        buf[i] = 255;
        buf[i + 1] = 59;
        buf[i + 2] = 71;
        buf[i + 3] = 255;
      } else {
        buf[i + 3] = 0;
      }
    }
  }
  void png;
  return nativeImage.createFromBuffer(buf, { width: size, height: size });
}

export function createTray(opts: {
  getMainWindow: () => BrowserWindow | null;
  onShow: () => void;
  onQuit: () => void;
  onRestartBackend: () => void;
  onOpenSessions: () => void;
}): Tray {
  const tray = new Tray(buildStatusIcon({ state: "idle" }));
  tray.setToolTip("Wallbreaker");

  const rebuildMenu = (status: BackendStatus) => {
    const label =
      status.state === "ready"
        ? `Backend: ready (${status.url})`
        : status.state === "starting"
          ? `Backend: starting :${status.port}`
          : status.state === "error"
            ? `Backend: error`
            : "Backend: idle";

    const context = Menu.buildFromTemplate([
      { label, enabled: false },
      { type: "separator" },
      { label: "Show Wallbreaker", click: () => opts.onShow() },
      { label: "Restart Backend", click: () => opts.onRestartBackend() },
      { label: "Open Sessions Folder", click: () => opts.onOpenSessions() },
      { type: "separator" },
      { label: "Quit", click: () => opts.onQuit() },
    ]);
    tray.setContextMenu(context);
    tray.setToolTip(
      status.state === "ready"
        ? `Wallbreaker — ${status.url}`
        : status.state === "error"
          ? `Wallbreaker — error: ${status.message}`
          : `Wallbreaker — ${status.state}`,
    );
    tray.setImage(buildStatusIcon(status));
  };

  rebuildMenu({ state: "idle" });

  tray.on("double-click", () => opts.onShow());
  tray.on("click", () => {
    if (process.platform === "win32") opts.onShow();
  });

  return Object.assign(tray, {
    updateStatus(status: BackendStatus) {
      rebuildMenu(status);
    },
  });
}

export type StatusTray = Tray & { updateStatus: (status: BackendStatus) => void };
