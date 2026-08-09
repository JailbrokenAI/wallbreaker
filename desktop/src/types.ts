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
  platform: NodeJS.Platform;
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
