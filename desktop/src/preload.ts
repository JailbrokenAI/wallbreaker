import { contextBridge, ipcRenderer } from "electron";
import type { BackendStatus, DesktopInfo, DesktopSettings, DiagnosticsReport } from "./types";

export type DesktopBridge = {
  getStatus: () => Promise<BackendStatus>;
  getSettings: () => Promise<DesktopSettings>;
  patchSettings: (partial: Partial<DesktopSettings>) => Promise<DesktopSettings>;
  getLog: () => Promise<string>;
  getInfo: () => Promise<DesktopInfo>;
  restartBackend: () => Promise<BackendStatus>;
  openExternal: (url: string) => Promise<void>;
  openPath: (target: string) => Promise<string>;
  showItemInFolder: (target: string) => Promise<void>;
  pickFile: (opts?: { title?: string; filters?: { name: string; extensions: string[] }[] }) => Promise<string | null>;
  notify: (title: string, body: string) => Promise<boolean>;
  diagnostics: () => Promise<DiagnosticsReport>;
  exportLog: (content: string) => Promise<string | null>;
  copyText: (text: string) => Promise<boolean>;
  navigate: (hash: string) => Promise<boolean>;
  platform: NodeJS.Platform;
  isDesktop: true;
  onStatus: (cb: (status: BackendStatus) => void) => () => void;
  onLog: (cb: (line: string) => void) => () => void;
  onCommandPalette: (cb: () => void) => () => void;
  onRunDiagnostics: (cb: () => void) => () => void;
  onShowShortcuts: (cb: () => void) => () => void;
};

function onChannel(channel: string, cb: (...args: unknown[]) => void): () => void {
  const listener = (_: Electron.IpcRendererEvent, ...args: unknown[]) => cb(...args);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

const bridge: DesktopBridge = {
  getStatus: () => ipcRenderer.invoke("desktop:get-status"),
  getSettings: () => ipcRenderer.invoke("desktop:get-settings"),
  patchSettings: (partial) => ipcRenderer.invoke("desktop:patch-settings", partial),
  getLog: () => ipcRenderer.invoke("desktop:get-log"),
  getInfo: () => ipcRenderer.invoke("desktop:get-info"),
  restartBackend: () => ipcRenderer.invoke("desktop:restart-backend"),
  openExternal: (url) => ipcRenderer.invoke("desktop:open-external", url),
  openPath: (target) => ipcRenderer.invoke("desktop:open-path", target),
  showItemInFolder: (target) => ipcRenderer.invoke("desktop:show-item", target),
  pickFile: (opts) => ipcRenderer.invoke("desktop:pick-file", opts ?? {}),
  notify: (title, body) => ipcRenderer.invoke("desktop:notify", { title, body }),
  diagnostics: () => ipcRenderer.invoke("desktop:diagnostics"),
  exportLog: (content) => ipcRenderer.invoke("desktop:export-log", content),
  copyText: (text) => ipcRenderer.invoke("desktop:copy-text", text),
  navigate: (hash) => ipcRenderer.invoke("desktop:navigate", hash),
  platform: process.platform,
  isDesktop: true,
  onStatus: (cb) => onChannel("desktop:status", (s) => cb(s as BackendStatus)),
  onLog: (cb) => onChannel("desktop:log", (line) => cb(String(line))),
  onCommandPalette: (cb) => onChannel("desktop:command-palette", () => cb()),
  onRunDiagnostics: (cb) => onChannel("desktop:run-diagnostics", () => cb()),
  onShowShortcuts: (cb) => onChannel("desktop:show-shortcuts", () => cb()),
};

contextBridge.exposeInMainWorld("wallbreakerDesktop", bridge);
