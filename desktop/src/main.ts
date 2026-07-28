import {
  BrowserWindow,
  Menu,
  Notification,
  app,
  dialog,
  globalShortcut,
  ipcMain,
  shell,
} from "electron";
import path from "node:path";
import { BackendManager, resolvePython } from "./backend";
import { runDiagnostics } from "./diagnostics";
import { buildAppMenu } from "./menu";
import { iconPath, projectRoot, splashPath } from "./paths";
import { getSettings, patchSettings } from "./store";
import { createTray, type StatusTray } from "./tray";
import type { BackendStatus, DesktopInfo } from "./types";

let mainWindow: BrowserWindow | null = null;
let tray: StatusTray | null = null;
let isQuitting = false;
const backend = new BackendManager();

function showMainWindow(): void {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function notify(title: string, body: string, opts?: { silent?: boolean; urgency?: "normal" | "critical" | "low" }): void {
  if (!Notification.isSupported()) return;
  try {
    const n = new Notification({
      title,
      body,
      silent: opts?.silent ?? true,
      urgency: opts?.urgency ?? "normal",
      icon: iconPath(),
    });
    n.on("click", () => showMainWindow());
    n.show();
  } catch {
    /* ignore */
  }
}

function createWindow(): BrowserWindow {
  const bounds = getSettings().windowBounds ?? { width: 1440, height: 920 };
  const icon = iconPath();

  const win = new BrowserWindow({
    width: bounds.width,
    height: bounds.height,
    x: bounds.x,
    y: bounds.y,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    backgroundColor: "#0b0809",
    title: "Wallbreaker",
    icon,
    autoHideMenuBar: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: false,
    },
  });

  win.once("ready-to-show", () => {
    if (!getSettings().startMinimized) win.show();
  });

  win.on("close", (e) => {
    if (isQuitting) return;
    if (getSettings().closeToTray) {
      e.preventDefault();
      win.hide();
      if (process.platform === "win32") {
        notify("Wallbreaker", "Still running in the tray. Right-click the icon to quit.");
      }
    }
  });

  win.on("resize", () => persistBounds(win));
  win.on("move", () => persistBounds(win));

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  // Keep desktop pages on local dashboard host when possible
  win.webContents.on("will-navigate", (event, url) => {
    const st = backend.getStatus();
    if (st.state === "ready" && url.startsWith("http") && !url.startsWith(st.url)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  return win;
}

function persistBounds(win: BrowserWindow): void {
  if (!win || win.isDestroyed() || win.isMinimized() || !win.isVisible()) return;
  const b = win.getBounds();
  patchSettings({
    windowBounds: { width: b.width, height: b.height, x: b.x, y: b.y },
  });
}

async function loadSplash(win: BrowserWindow, message: string): Promise<void> {
  const file = splashPath();
  await win.loadFile(file, { query: { msg: message } });
}

function broadcastStatus(status: BackendStatus): void {
  tray?.updateStatus(status);
  BrowserWindow.getAllWindows().forEach((w) => {
    if (!w.isDestroyed()) w.webContents.send("desktop:status", status);
  });
  if (mainWindow && !mainWindow.isDestroyed()) {
    const suffix =
      status.state === "ready"
        ? ` — ${status.url.replace("http://", "")}`
        : status.state === "error"
          ? " — backend error"
          : status.state === "starting"
            ? " — starting…"
            : "";
    mainWindow.setTitle(`Wallbreaker${suffix}`);
  }
}

function openDesktopSettings(): void {
  const win = mainWindow;
  if (!win) return;
  const st = backend.getStatus();
  if (st.state === "ready") {
    win.loadURL(`${st.url}#settings`).catch(() => undefined);
    // Ask renderer to scroll/focus desktop card
    setTimeout(() => {
      win.webContents
        .executeJavaScript(
          `window.dispatchEvent(new CustomEvent('wallbreaker:open-desktop-settings'))`,
        )
        .catch(() => undefined);
    }, 300);
  }
}

async function boot(): Promise<void> {
  const settings = getSettings();
  mainWindow = createWindow();
  const win = mainWindow;

  tray = createTray({
    getMainWindow: () => mainWindow,
    onShow: showMainWindow,
    onQuit: () => {
      isQuitting = true;
      app.quit();
    },
    onRestartBackend: () => {
      restartBackend().catch((err) => {
        dialog.showErrorBox("Backend restart failed", String(err));
      });
    },
    onOpenSessions: () => {
      shell.openPath(path.join(projectRoot(), "sessions"));
    },
  }) as StatusTray;

  Menu.setApplicationMenu(
    buildAppMenu({
      mainWindow: () => mainWindow,
      backend,
      onReloadUi: () => {
        const st = backend.getStatus();
        if (st.state === "ready" && mainWindow) {
          mainWindow.loadURL(st.url).catch(() => undefined);
        }
      },
      onRestartBackend: () => {
        restartBackend().catch((err) => dialog.showErrorBox("Backend restart failed", String(err)));
      },
      onToggleDevTools: () => mainWindow?.webContents.toggleDevTools(),
      onOpenDesktopSettings: openDesktopSettings,
    }),
  );

  backend.on("status", (status: BackendStatus) => broadcastStatus(status));
  backend.on("log", (line: string) => {
    BrowserWindow.getAllWindows().forEach((w) => {
      if (!w.isDestroyed()) w.webContents.send("desktop:log", line);
    });
  });

  await loadSplash(win, "Starting Wallbreaker backend…");
  if (!getSettings().startMinimized) win.show();

  try {
    const { url } = await backend.start({
      host: settings.host,
      port: settings.port,
      pythonPath: settings.pythonPath || undefined,
      configPath: settings.configPath || undefined,
    });
    await win.loadURL(url);
    backend.startHealthMonitor(settings.autoReconnect);
    if (settings.openDevTools) win.webContents.openDevTools({ mode: "detach" });
    notify("Wallbreaker", `Dashboard ready at ${url}`);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const log = backend.getLogTail(120);
    await loadSplash(
      win,
      encodeURIComponent(
        `Backend failed to start.\n\n${message}\n\n--- log ---\n${log}\n\nRoot: ${projectRoot()}`,
      ),
    );
    dialog.showErrorBox(
      "Wallbreaker backend failed",
      `${message}\n\nProject root: ${projectRoot()}\n\nEnsure:\n1) pip install -e ".[dashboard]"\n2) cd wallbreaker/dashboard/web && npm i && npm run build`,
    );
  }
}

async function restartBackend(): Promise<void> {
  if (!mainWindow) return;
  backend.stopHealthMonitor();
  await loadSplash(mainWindow, "Restarting backend…");
  const settings = getSettings();
  try {
    const { url } = await backend.restart({
      host: settings.host,
      port: settings.port,
      pythonPath: settings.pythonPath || undefined,
      configPath: settings.configPath || undefined,
    });
    await mainWindow.loadURL(url);
    backend.startHealthMonitor(settings.autoReconnect);
    notify("Wallbreaker", "Backend restarted");
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    await loadSplash(
      mainWindow,
      encodeURIComponent(`Restart failed.\n\n${message}\n\n${backend.getLogTail(80)}`),
    );
    throw err;
  }
}

function getInfo(): DesktopInfo {
  const root = projectRoot();
  const s = getSettings();
  const st = backend.getStatus();
  return {
    version: app.getVersion(),
    platform: process.platform,
    arch: process.arch,
    projectRoot: root,
    pythonResolved: resolvePython(root, s.pythonPath || undefined),
    isPackaged: app.isPackaged,
    userData: app.getPath("userData"),
    backendUrl: st.state === "ready" ? st.url : "",
  };
}

function sendToRenderer(channel: string, payload?: unknown): void {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send(channel, payload);
}

function navigateHash(hash: string): void {
  const win = mainWindow;
  if (!win) return;
  const st = backend.getStatus();
  if (st.state === "ready") {
    const clean = hash.startsWith("#") ? hash : `#${hash}`;
    win.loadURL(`${st.url}${clean}`).catch(() => undefined);
  }
}

function registerIpc(): void {
  ipcMain.handle("desktop:get-status", () => backend.getStatus());
  ipcMain.handle("desktop:get-settings", () => getSettings());
  ipcMain.handle("desktop:patch-settings", (_e, partial) => {
    const next = patchSettings(partial ?? {});
    // live-apply reconnect flag
    if (backend.getStatus().state === "ready") {
      backend.startHealthMonitor(next.autoReconnect);
    }
    return next;
  });
  ipcMain.handle("desktop:get-log", () => backend.getLogTail(200));
  ipcMain.handle("desktop:get-info", () => getInfo());
  ipcMain.handle("desktop:restart-backend", async () => {
    await restartBackend();
    return backend.getStatus();
  });
  ipcMain.handle("desktop:open-external", async (_e, url: string) => {
    if (typeof url === "string" && /^(https?:|mailto:)/i.test(url)) {
      await shell.openExternal(url);
    }
  });
  ipcMain.handle("desktop:open-path", async (_e, target: string) => {
    if (typeof target !== "string") return "invalid";
    return shell.openPath(target);
  });
  ipcMain.handle("desktop:show-item", async (_e, target: string) => {
    if (typeof target === "string") shell.showItemInFolder(target);
  });
  ipcMain.handle(
    "desktop:pick-file",
    async (
      _e,
      opts: { title?: string; filters?: { name: string; extensions: string[] }[] },
    ) => {
      const res = await dialog.showOpenDialog(mainWindow ?? undefined!, {
        title: opts?.title ?? "Select file",
        properties: ["openFile"],
        filters: opts?.filters,
      });
      if (res.canceled || !res.filePaths[0]) return null;
      return res.filePaths[0];
    },
  );
  ipcMain.handle("desktop:notify", (_e, payload: { title?: string; body?: string }) => {
    const title = String(payload?.title || "Wallbreaker").slice(0, 120);
    const body = String(payload?.body || "").slice(0, 400);
    notify(title, body, { silent: false, urgency: "critical" });
    return true;
  });
  ipcMain.handle("desktop:diagnostics", async () => runDiagnostics(backend.getStatus()));
  ipcMain.handle("desktop:export-log", async (_e, content: string) => {
    const res = await dialog.showSaveDialog(mainWindow ?? undefined!, {
      title: "Export Wallbreaker log",
      defaultPath: path.join(app.getPath("documents"), `wallbreaker-log-${Date.now()}.txt`),
      filters: [
        { name: "Text", extensions: ["txt", "log"] },
        { name: "All", extensions: ["*"] },
      ],
    });
    if (res.canceled || !res.filePath) return null;
    const fs = await import("node:fs/promises");
    await fs.writeFile(res.filePath, String(content ?? ""), "utf8");
    return res.filePath;
  });
  ipcMain.handle("desktop:copy-text", async (_e, text: string) => {
    const { clipboard } = await import("electron");
    clipboard.writeText(String(text ?? ""));
    return true;
  });
  ipcMain.handle("desktop:navigate", (_e, hash: string) => {
    navigateHash(String(hash || ""));
    return true;
  });
}

function registerShortcuts(): void {
  try {
    globalShortcut.register("CommandOrControl+Shift+W", () => {
      if (!mainWindow) return;
      if (mainWindow.isVisible() && mainWindow.isFocused()) mainWindow.hide();
      else showMainWindow();
    });
  } catch {
    /* ignore */
  }

  // In-window shortcuts via before-input-event (more reliable than global for palette)
  app.on("browser-window-created", (_e, win) => {
    win.webContents.on("before-input-event", (event, input) => {
      if (input.type !== "keyDown") return;
      const ctrl = input.control || input.meta;
      if (ctrl && !input.shift && !input.alt && input.key.toLowerCase() === "k") {
        event.preventDefault();
        sendToRenderer("desktop:command-palette");
      }
      if (ctrl && input.shift && input.key.toLowerCase() === "d") {
        event.preventDefault();
        sendToRenderer("desktop:run-diagnostics");
      }
      if (ctrl && input.key === "/") {
        event.preventDefault();
        sendToRenderer("desktop:show-shortcuts");
      }
    });
  });
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => showMainWindow());

  app.whenReady().then(async () => {
    registerIpc();
    registerShortcuts();
    await boot();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        boot().catch(console.error);
      } else {
        showMainWindow();
      }
    });
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin" && !getSettings().closeToTray) {
      app.quit();
    }
  });

  app.on("will-quit", () => {
    globalShortcut.unregisterAll();
    backend.stopHealthMonitor();
  });

  let cleanedUp = false;
  app.on("before-quit", (e) => {
    isQuitting = true;
    if (cleanedUp) return;
    e.preventDefault();
    cleanedUp = true;
    backend.stopHealthMonitor();
    backend
      .stop()
      .catch(() => undefined)
      .finally(() => app.exit(0));
  });
}
