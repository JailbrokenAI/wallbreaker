import { useEffect, useState } from "react";
import { desktop, isDesktop, type BackendStatus } from "../desktop";
import { zh } from "../i18n/zh";

export function DesktopStatus() {
  const [status, setStatus] = useState<BackendStatus | null>(null);

  useEffect(() => {
    if (!isDesktop()) return;
    const api = desktop()!;
    api.getStatus().then(setStatus).catch(() => undefined);
    return api.onStatus(setStatus);
  }, []);

  if (!isDesktop() || !status) return null;

  const cls =
    status.state === "ready"
      ? "ok"
      : status.state === "starting"
        ? "warn"
        : status.state === "error"
          ? "bad"
          : "idle";

  const text =
    status.state === "ready"
      ? status.owned === false
        ? zh.status.ext
        : zh.status.on
      : status.state === "starting"
        ? "…"
        : status.state === "error"
          ? zh.status.err
          : zh.status.off;

  const title =
    status.state === "ready"
      ? `后端就绪：${status.url}${status.owned === false ? "（外部）" : ""}`
      : status.state === "error"
        ? status.message
        : status.state;

  return (
    <span className={`pill desktop-status ${cls}`} title={title}>
      <span className="dot-live" />
      {text}
    </span>
  );
}
