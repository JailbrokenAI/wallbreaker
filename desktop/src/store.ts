import Store from "electron-store";
import type { DesktopSettings } from "./types";

const defaults: DesktopSettings = {
  host: "127.0.0.1",
  port: 8787,
  startMinimized: false,
  closeToTray: true,
  openDevTools: false,
  autoReconnect: true,
  notifyOnComply: true,
  pythonPath: "",
  configPath: "",
  windowBounds: { width: 1440, height: 920 },
};

export const settings = new Store<DesktopSettings>({
  name: "wallbreaker-desktop",
  defaults,
});

export function getSettings(): DesktopSettings {
  return {
    host: settings.get("host"),
    port: settings.get("port"),
    startMinimized: settings.get("startMinimized"),
    closeToTray: settings.get("closeToTray"),
    openDevTools: settings.get("openDevTools"),
    autoReconnect: settings.get("autoReconnect"),
    notifyOnComply: settings.get("notifyOnComply"),
    pythonPath: settings.get("pythonPath"),
    configPath: settings.get("configPath"),
    windowBounds: settings.get("windowBounds"),
  };
}

export function patchSettings(partial: Partial<DesktopSettings>): DesktopSettings {
  for (const [k, v] of Object.entries(partial)) {
    if (v !== undefined) settings.set(k as keyof DesktopSettings, v as never);
  }
  return getSettings();
}
