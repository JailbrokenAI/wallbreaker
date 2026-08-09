export type BackendStatus =
  | { state: "idle" }
  | { state: "starting"; port: number; detail?: string }
  | { state: "ready"; port: number; url: string; owned?: boolean }
  | { state: "error"; message: string; logTail?: string };

export interface DesktopSettings {
  host: string;
  port: number;
  startMinimized: boolean;
  closeToTray: boolean;
  openDevTools: boolean;
  autoReconnect: boolean;
  notifyOnComply: boolean;
  pythonPath: string;
  configPath: string;
  windowBounds: { width: number; height: number; x?: number; y?: number } | null;
}

export interface DesktopInfo {
  version: string;
  platform: string;
  arch: string;
  projectRoot: string;
  pythonResolved: string;
  isPackaged: boolean;
  userData: string;
  backendUrl?: string;
}

export interface DiagnosticCheck {
  id: string;
  label: string;
  ok: boolean;
  detail: string;
}

export interface DiagnosticsReport {
  ok: boolean;
  generatedAt: string;
  checks: DiagnosticCheck[];
  summary: string;
}

export interface WallbreakerDesktopBridge {
  getStatus: () => Promise<BackendStatus>;
  getSettings: () => Promise<DesktopSettings>;
  patchSettings: (partial: Partial<DesktopSettings>) => Promise<DesktopSettings>;
  getLog: () => Promise<string>;
  getInfo: () => Promise<DesktopInfo>;
  restartBackend: () => Promise<BackendStatus>;
  openExternal: (url: string) => Promise<void>;
  openPath: (target: string) => Promise<string>;
  showItemInFolder: (target: string) => Promise<void>;
  pickFile: (opts?: {
    title?: string;
    filters?: { name: string; extensions: string[] }[];
  }) => Promise<string | null>;
  notify: (title: string, body: string) => Promise<boolean>;
  diagnostics: () => Promise<DiagnosticsReport>;
  exportLog: (content: string) => Promise<string | null>;
  copyText: (text: string) => Promise<boolean>;
  navigate: (hash: string) => Promise<boolean>;
  platform: string;
  isDesktop: true;
  onStatus: (cb: (status: BackendStatus) => void) => () => void;
  onLog: (cb: (line: string) => void) => () => void;
  onCommandPalette?: (cb: () => void) => () => void;
  onRunDiagnostics?: (cb: () => void) => () => void;
  onShowShortcuts?: (cb: () => void) => () => void;
}

declare global {
  interface Window {
    wallbreakerDesktop?: WallbreakerDesktopBridge;
  }
}

/** True when running inside the Electron shell. */
export function isDesktop(): boolean {
  return typeof window !== "undefined" && !!window.wallbreakerDesktop?.isDesktop;
}

export function desktop(): WallbreakerDesktopBridge | null {
  return window.wallbreakerDesktop ?? null;
}
