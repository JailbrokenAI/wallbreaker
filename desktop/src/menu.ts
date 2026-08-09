import { BrowserWindow, Menu, MenuItemConstructorOptions, app, dialog, shell } from "electron";
import type { BackendManager } from "./backend";
import { projectRoot } from "./paths";

export function buildAppMenu(opts: {
  mainWindow: () => BrowserWindow | null;
  backend: BackendManager;
  onReloadUi: () => void;
  onRestartBackend: () => void;
  onToggleDevTools: () => void;
  onOpenDesktopSettings: () => void;
}): Menu {
  const isMac = process.platform === "darwin";

  const file: MenuItemConstructorOptions = {
    label: "File",
    submenu: [
      {
        label: "Reload UI",
        accelerator: "CmdOrCtrl+R",
        click: () => opts.onReloadUi(),
      },
      {
        label: "Restart Backend",
        accelerator: "CmdOrCtrl+Shift+R",
        click: () => opts.onRestartBackend(),
      },
      {
        label: "Desktop Settings…",
        accelerator: "CmdOrCtrl+,",
        click: () => opts.onOpenDesktopSettings(),
      },
      {
        label: "Command Palette…",
        accelerator: "CmdOrCtrl+K",
        click: () => {
          const win = opts.mainWindow();
          win?.webContents.send("desktop:command-palette");
        },
      },
      {
        label: "Run Diagnostics",
        accelerator: "CmdOrCtrl+Shift+D",
        click: () => {
          const win = opts.mainWindow();
          win?.webContents.send("desktop:run-diagnostics");
        },
      },
      { type: "separator" },
      {
        label: "Open Project Folder",
        click: () => shell.openPath(projectRoot()),
      },
      {
        label: "Open Sessions Folder",
        click: () => shell.openPath(`${projectRoot()}/sessions`),
      },
      {
        label: "Open Config",
        click: () => shell.openPath(`${projectRoot()}/config.toml`),
      },
      { type: "separator" },
      isMac ? { role: "close" } : { role: "quit" },
    ],
  };

  const view: MenuItemConstructorOptions = {
    label: "View",
    submenu: [
      { role: "reload", visible: false },
      { role: "forceReload", visible: false },
      {
        label: "Toggle Developer Tools",
        accelerator: process.platform === "darwin" ? "Alt+Command+I" : "Ctrl+Shift+I",
        click: () => opts.onToggleDevTools(),
      },
      { type: "separator" },
      { role: "resetZoom" },
      { role: "zoomIn" },
      { role: "zoomOut" },
      { type: "separator" },
      { role: "togglefullscreen" },
    ],
  };

  const navigate: MenuItemConstructorOptions = {
    label: "Navigate",
    submenu: [
      { label: "Agent", accelerator: "CmdOrCtrl+1", click: () => go("#agent") },
      { label: "Overview", accelerator: "CmdOrCtrl+2", click: () => go("#overview") },
      { label: "Attack console", accelerator: "CmdOrCtrl+3", click: () => go("#console") },
      { label: "Terminal", accelerator: "CmdOrCtrl+4", click: () => go("#terminal") },
      { label: "Findings", accelerator: "CmdOrCtrl+5", click: () => go("#findings") },
      { label: "Run logs", accelerator: "CmdOrCtrl+6", click: () => go("#runs") },
      { label: "Arsenal", accelerator: "CmdOrCtrl+7", click: () => go("#arsenal") },
      { label: "Profiles", accelerator: "CmdOrCtrl+8", click: () => go("#profiles") },
      { label: "Settings", accelerator: "CmdOrCtrl+9", click: () => go("#settings") },
    ],
  };

  const help: MenuItemConstructorOptions = {
    label: "Help",
    submenu: [
      {
        label: "Wallbreaker on GitHub",
        click: () => shell.openExternal("https://github.com/JailbrokenAI/wallbreaker"),
      },
      {
        label: "Keyboard Shortcuts",
        accelerator: "CmdOrCtrl+/",
        click: () => {
          const win = opts.mainWindow();
          win?.webContents.send("desktop:show-shortcuts");
        },
      },
      {
        label: "Desktop README",
        click: () => shell.openPath(`${projectRoot()}/desktop/README.md`),
      },
      {
        label: "Responsible use (SECURITY.md)",
        click: () => shell.openPath(`${projectRoot()}/SECURITY.md`),
      },
      { type: "separator" },
      {
        label: "About Wallbreaker",
        click: () => {
          const win = opts.mainWindow();
          const status = opts.backend.getStatus();
          const detail =
            status.state === "ready"
              ? `Backend: ${status.url}${status.owned === false ? " (external)" : ""}`
              : status.state === "error"
                ? `Backend error: ${status.message}`
                : `Backend: ${status.state}`;
          dialog.showMessageBox(win ?? (undefined as unknown as BrowserWindow), {
            type: "info",
            title: "About Wallbreaker",
            message: "Wallbreaker Desktop",
            detail: `Version ${app.getVersion()}\n${detail}\nRoot: ${projectRoot()}\n\nAuthorized LLM red-teaming only.`,
          });
        },
      },
    ],
  };

  function go(hash: string): void {
    const win = opts.mainWindow();
    if (!win) return;
    const url = win.webContents.getURL();
    if (url.startsWith("http")) {
      const base = url.split("#")[0];
      win.loadURL(base + hash).catch(() => undefined);
    }
  }

  const template: MenuItemConstructorOptions[] = [];
  if (isMac) {
    template.push({
      label: app.name,
      submenu: [
        { role: "about" },
        { type: "separator" },
        { role: "services" },
        { type: "separator" },
        { role: "hide" },
        { role: "hideOthers" },
        { role: "unhide" },
        { type: "separator" },
        { role: "quit" },
      ],
    });
  }
  template.push(file, view, navigate, help);
  return Menu.buildFromTemplate(template);
}
