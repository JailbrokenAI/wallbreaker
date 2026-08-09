import { useEffect, useState } from "react";
import {
  desktop,
  isDesktop,
  type BackendStatus,
  type DesktopInfo,
  type DesktopSettings,
} from "../desktop";
import { zh } from "../i18n/zh";

export function DesktopPanel() {
  const api = desktop();
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [info, setInfo] = useState<DesktopInfo | null>(null);
  const [status, setStatus] = useState<BackendStatus | null>(null);
  const [log, setLog] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [draft, setDraft] = useState<Partial<DesktopSettings>>({});

  const refresh = async () => {
    if (!api) return;
    const [s, i, st, l] = await Promise.all([
      api.getSettings(),
      api.getInfo(),
      api.getStatus(),
      api.getLog(),
    ]);
    setSettings(s);
    setDraft(s);
    setInfo(i);
    setStatus(st);
    setLog(l);
  };

  useEffect(() => {
    if (!api) return;
    refresh().catch(() => undefined);
    const offStatus = api.onStatus(setStatus);
    const offLog = api.onLog((line) => {
      setLog((prev) => {
        const next = (prev ? prev + "\n" : "") + line;
        const lines = next.split("\n");
        return lines.slice(-200).join("\n");
      });
    });
    const onOpen = () => {
      document.getElementById("desktop-shell-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    window.addEventListener("wallbreaker:open-desktop-settings", onOpen);
    return () => {
      offStatus();
      offLog();
      window.removeEventListener("wallbreaker:open-desktop-settings", onOpen);
    };
  }, [api]);

  if (!isDesktop() || !api) return null;

  const save = async (restart = false) => {
    if (!draft) return;
    setBusy(true);
    setMsg(null);
    try {
      const next = await api.patchSettings({
        host: draft.host,
        port: Number(draft.port) || 8787,
        startMinimized: !!draft.startMinimized,
        closeToTray: !!draft.closeToTray,
        openDevTools: !!draft.openDevTools,
        autoReconnect: !!draft.autoReconnect,
        notifyOnComply: draft.notifyOnComply !== false,
        pythonPath: draft.pythonPath ?? "",
        configPath: draft.configPath ?? "",
      });
      setSettings(next);
      setDraft(next);
      setMsg(restart ? zh.desktop.savedRestart : zh.desktop.saved);
      if (restart) {
        await api.restartBackend();
        setMsg(zh.desktop.restarted);
        await refresh();
      }
    } catch (err) {
      setMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const pickPython = async () => {
    const p = await api.pickFile({
      title: "Select Python executable",
      filters: [
        { name: "Python", extensions: ["exe"] },
        { name: "All", extensions: ["*"] },
      ],
    });
    if (p) setDraft((d) => ({ ...d, pythonPath: p }));
  };

  const pickConfig = async () => {
    const p = await api.pickFile({
      title: "Select config.toml",
      filters: [
        { name: "TOML", extensions: ["toml"] },
        { name: "All", extensions: ["*"] },
      ],
    });
    if (p) setDraft((d) => ({ ...d, configPath: p }));
  };

  const statusLabel = (() => {
    if (!status) return "…";
    if (status.state === "ready") return `就绪 · ${status.url}${status.owned === false ? " · 外部" : ""}`;
    if (status.state === "starting") return `启动中 :${status.port}`;
    if (status.state === "error") return `错误 · ${status.message}`;
    return status.state;
  })();

  return (
    <div className="card settings-wide" id="desktop-shell-card">
      <h3>{zh.desktop.title}</h3>
      <div className="muted" style={{ fontSize: 12, marginBottom: 12 }}>
        {zh.desktop.hint}
      </div>

      <div className="desktop-meta-grid">
        <div>
          <div className="lbl">{zh.desktop.backend}</div>
          <div className="val mono">{statusLabel}</div>
        </div>
        <div>
          <div className="lbl">{zh.desktop.app}</div>
          <div className="val mono">
            v{info?.version ?? "?"} · {info?.platform}/{info?.arch}
          </div>
        </div>
        <div>
          <div className="lbl">{zh.desktop.python}</div>
          <div className="val mono truncate" title={info?.pythonResolved}>
            {info?.pythonResolved || "—"}
          </div>
        </div>
        <div>
          <div className="lbl">{zh.desktop.projectRoot}</div>
          <div className="val mono truncate" title={info?.projectRoot}>
            {info?.projectRoot || "—"}
          </div>
        </div>
      </div>

      <div className="desktop-form">
        <label>
          {zh.desktop.host}
          <input
            value={draft.host ?? ""}
            onChange={(e) => setDraft((d) => ({ ...d, host: e.target.value }))}
            spellCheck={false}
          />
        </label>
        <label>
          {zh.desktop.port}
          <input
            type="number"
            min={1}
            max={65535}
            value={draft.port ?? 8787}
            onChange={(e) => setDraft((d) => ({ ...d, port: Number(e.target.value) }))}
          />
        </label>
        <label className="span-2">
          {zh.desktop.pythonPath}
          <div className="row-input">
            <input
              value={draft.pythonPath ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, pythonPath: e.target.value }))}
              placeholder={zh.desktop.pythonAuto}
              spellCheck={false}
            />
            <button type="button" className="ghost-command" onClick={pickPython}>
              {zh.common.browse}
            </button>
          </div>
        </label>
        <label className="span-2">
          {zh.desktop.configPath}
          <div className="row-input">
            <input
              value={draft.configPath ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, configPath: e.target.value }))}
              placeholder={zh.desktop.configAuto}
              spellCheck={false}
            />
            <button type="button" className="ghost-command" onClick={pickConfig}>
              {zh.common.browse}
            </button>
          </div>
        </label>
      </div>

      <div className="desktop-toggles">
        <label className="check">
          <input
            type="checkbox"
            checked={!!draft.closeToTray}
            onChange={(e) => setDraft((d) => ({ ...d, closeToTray: e.target.checked }))}
          />
          {zh.desktop.closeToTray}
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={!!draft.startMinimized}
            onChange={(e) => setDraft((d) => ({ ...d, startMinimized: e.target.checked }))}
          />
          {zh.desktop.startMinimized}
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={!!draft.autoReconnect}
            onChange={(e) => setDraft((d) => ({ ...d, autoReconnect: e.target.checked }))}
          />
          {zh.desktop.autoReconnect}
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.notifyOnComply !== false}
            onChange={(e) => setDraft((d) => ({ ...d, notifyOnComply: e.target.checked }))}
          />
          {zh.desktop.notifyOnComply}
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={!!draft.openDevTools}
            onChange={(e) => setDraft((d) => ({ ...d, openDevTools: e.target.checked }))}
          />
          {zh.desktop.openDevTools}
        </label>
      </div>

      <div className="desktop-actions">
        <button type="button" className="ghost-command" disabled={busy} onClick={() => save(false)}>
          {zh.desktop.save}
        </button>
        <button type="button" className="primary-command" disabled={busy} onClick={() => save(true)}>
          {zh.desktop.saveRestart}
        </button>
        <button
          type="button"
          className="ghost-command"
          disabled={busy}
          onClick={() => api.restartBackend().then(refresh)}
        >
          {zh.desktop.restartOnly}
        </button>
        <button
          type="button"
          className="ghost-command"
          onClick={() => info && api.openPath(info.projectRoot)}
        >
          {zh.desktop.openProject}
        </button>
        <button
          type="button"
          className="ghost-command"
          onClick={() => info && api.openPath(`${info.projectRoot}/sessions`)}
        >
          {zh.desktop.openSessions}
        </button>
        <button
          type="button"
          className="ghost-command"
          onClick={() => settings && api.getLog().then(setLog)}
        >
          {zh.desktop.refreshLog}
        </button>
        <button
          type="button"
          className="ghost-command"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setMsg(null);
            try {
              const report = await api.diagnostics();
              setMsg(`${report.ok ? "正常" : "存在问题"} — ${report.summary}`);
              setLog(
                report.checks
                  .map((c) => `${c.ok ? "PASS" : "FAIL"}  ${c.label}: ${c.detail}`)
                  .join("\n"),
              );
            } catch (err) {
              setMsg(err instanceof Error ? err.message : String(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          {zh.desktop.runDiagnostics}
        </button>
        <button
          type="button"
          className="ghost-command"
          onClick={async () => {
            await api.notify("Daedalus", zh.desktop.testNotifyBody);
            setMsg(zh.desktop.testNotifySent);
          }}
        >
          {zh.desktop.testNotify}
        </button>
      </div>

      {msg && <div className="desktop-msg">{msg}</div>}

      <details className="desktop-log" open={status?.state === "error"}>
        <summary>{zh.desktop.backendLog}</summary>
        <pre>{log || "—"}</pre>
      </details>
    </div>
  );
}
