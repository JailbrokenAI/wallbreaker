import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  runAgent,
  verdictKind,
  type AgentConfig,
  type AgentEvent,
  type AgentProfile,
  type Tool,
} from "../api";
import { AgentConfigDrawer, DEFAULT_AGENT_CONFIG, normalizeAgentConfig } from "./AgentConfigDrawer";
import { ModelChooser } from "./ModelChooser";
import { ProviderChooser } from "./ProviderChooser";
import { activityFromAgentEvent } from "../activityLog";
import { maybeNotifyVerdict } from "../notify";
import { zh } from "../i18n/zh";

type DaedalusMode = "CODE" | "LIBERATE" | "REPLAY";

type Item =
  | { kind: "text"; text: string }
  | { kind: "round"; round: number; max: number }
  | { kind: "tool_start"; name: string; args: string }
  | { kind: "tool_result"; name: string; content: string; error: boolean; verdict: string }
  | { kind: "progress"; text: string }
  | { kind: "feedback"; text: string }
  | { kind: "control"; text: string }
  | { kind: "mode"; mode: DaedalusMode; source: string; text: string }
  | { kind: "start"; brain: string; target: string }
  | { kind: "done"; status: string; summary: string }
  | { kind: "error"; error: string };

const DONE_KIND: Record<string, "bypass" | "held" | "neutral" | "error"> = {
  finished: "bypass",
  ask: "neutral",
  stuck: "neutral",
  max_rounds: "held",
  stopped: "held",
  error: "error",
};
const TECHNIQUE_STORE = "wallbreaker.agentTechniques";
const AGENT_SESSION_STORE = "wallbreaker.agentSession.v1";

function storedTechniques(): string[] | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(TECHNIQUE_STORE) || "null");
    return Array.isArray(value) && value.every((name) => typeof name === "string") ? value : null;
  } catch {
    return null;
  }
}

type AgentSession = {
  objective?: string;
  items?: Item[];
  runLog?: string;
  err?: string;
  currentAttacker?: { provider: string; model: string };
};

function loadAgentSession(): AgentSession {
  try {
    const raw = window.sessionStorage.getItem(AGENT_SESSION_STORE);
    if (!raw) return {};
    const value = JSON.parse(raw) as AgentSession;
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function saveAgentSession(patch: AgentSession): void {
  try {
    const prev = loadAgentSession();
    const next = { ...prev, ...patch };
    // Cap transcript size so sessionStorage does not blow up.
    if (Array.isArray(next.items) && next.items.length > 400) {
      next.items = next.items.slice(-400);
    }
    window.sessionStorage.setItem(AGENT_SESSION_STORE, JSON.stringify(next));
  } catch {
    /* ignore quota / private mode */
  }
}

export function Agent({ hasTarget }: { hasTarget: boolean }) {
  const restored = useMemo(() => loadAgentSession(), []);
  const [objective, setObjective] = useState(restored.objective || "");
  const [agentConfig, setAgentConfig] = useState<AgentConfig>(DEFAULT_AGENT_CONFIG);
  const [techniques, setTechniques] = useState<Tool[]>([]);
  const [enabled, setEnabled] = useState<Set<string>>(new Set());
  const [techniqueQuery, setTechniqueQuery] = useState("");
  const [items, setItems] = useState<Item[]>(Array.isArray(restored.items) ? restored.items : []);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const [pauseReady, setPauseReady] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [currentAttacker, setCurrentAttacker] = useState(
    restored.currentAttacker || { provider: "", model: "" },
  );
  const [steering, setSteering] = useState("");
  const [controlBusy, setControlBusy] = useState(false);
  const [runLog, setRunLog] = useState(restored.runLog || "");
  const [savingConfig, setSavingConfig] = useState(false);
  const [configStatus, setConfigStatus] = useState("");
  const [err, setErr] = useState(restored.err || "");
  const [daedalusMode, setDaedalusMode] = useState<DaedalusMode>("CODE");
  const runningRef = useRef(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stopPollRef = useRef<number | null>(null);

  function clearStopPoll() {
    if (stopPollRef.current != null) {
      window.clearInterval(stopPollRef.current);
      stopPollRef.current = null;
    }
  }

  function forceEndUi(summary = "operator ended the run") {
    clearStopPoll();
    try {
      abortRef.current?.abort();
    } catch {
      /* ignore */
    }
    abortRef.current = null;
    runningRef.current = false;
    setRunning(false);
    setPaused(false);
    setPauseReady(false);
    setStopping(false);
    setControlBusy(false);
    setItems((prev) => {
      if (prev.some((it) => it.kind === "done" && it.status === "stopped")) return prev;
      return [...prev, { kind: "done", status: "stopped", summary }];
    });
  }

  function startStopWatchdog() {
    clearStopPoll();
    let ticks = 0;
    stopPollRef.current = window.setInterval(() => {
      ticks += 1;
      void api.agentStatus()
        .then((status) => {
          if (!status.active) {
            forceEndUi("operator ended the run");
            return;
          }
          setStopping(!!status.stopping || true);
          setPaused(!!status.paused);
          setPauseReady(!!status.pause_ready);
          // Hard ceiling: if backend is still "active" after ~90s of stop attempts,
          // keep UI unlockable rather than permanent "正在结束".
          if (ticks >= 90) {
            forceEndUi("stop timed out — backend may still be draining; refresh if needed");
          }
        })
        .catch(() => {
          // Backend unreachable: unlock UI so the operator is not stuck.
          if (ticks >= 3) forceEndUi("stop: backend unreachable");
        });
    }, 1000);
  }

  useEffect(() => {
    api.settings()
      .then((settings) => setAgentConfig(normalizeAgentConfig(settings.agent)))
      .catch(() => {});
    api.tools().then((all) => {
      const selectable = all.filter((tool) => !tool.control);
      const known = new Set(selectable.map((tool) => tool.name));
      const saved = storedTechniques();
      const initial = saved === null ? known : new Set(saved.filter((name) => known.has(name)));
      setTechniques(selectable);
      setEnabled(initial);
    }).catch(() => {});
    // If a run is still active on the backend, reflect control state after remount.
    const statusRequest = api.agentStatus?.();
    statusRequest?.then((status) => {
      if (!status.active) return;
      setRunning(true);
      runningRef.current = true;
      setPaused(!!status.paused);
      setPauseReady(!!status.pause_ready);
      setStopping(!!status.stopping);
      setCurrentAttacker({ provider: status.provider || "", model: status.attacker || "" });
      if (status.objective) setObjective((prev) => prev || status.objective || "");
      if (status.stopping) startStopWatchdog();
    }).catch(() => {});
    return () => {
      clearStopPoll();
      try {
        abortRef.current?.abort();
      } catch {
        /* ignore */
      }
    };
  }, []);

  useEffect(() => {
    saveAgentSession({
      objective,
      items,
      runLog,
      err,
      currentAttacker,
    });
  }, [objective, items, runLog, err, currentAttacker]);

  const filteredTechniques = useMemo(() => {
    const needle = techniqueQuery.trim().toLowerCase();
    return techniques.filter((tool) => !needle
      || tool.name.toLowerCase().includes(needle)
      || tool.description.toLowerCase().includes(needle));
  }, [techniqueQuery, techniques]);

  function saveEnabled(next: Set<string>) {
    setEnabled(next);
    window.localStorage.setItem(TECHNIQUE_STORE, JSON.stringify([...next]));
  }

  function toggleTechnique(name: string) {
    const next = new Set(enabled);
    if (next.has(name)) next.delete(name); else next.add(name);
    saveEnabled(next);
  }

  function push(it: Item) {
    const pinned = isPinnedToBottom(bodyRef.current);
    setItems((prev) => {
      if (it.kind === "text" && prev.length && prev[prev.length - 1].kind === "text") {
        const copy = prev.slice();
        const last = copy[copy.length - 1] as { kind: "text"; text: string };
        copy[copy.length - 1] = { kind: "text", text: last.text + it.text };
        return copy;
      }
      return [...prev, it];
    });
    if (!pinned || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    requestAnimationFrame(() => {
      if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    });
  }

  function onEvent(ev: AgentEvent) {
    if (typeof ev.run_log === "string" && ev.run_log) setRunLog(ev.run_log);
    activityFromAgentEvent(ev);
    if (ev.type === "tool_result") {
      maybeNotifyVerdict(String(ev.verdict || ""), {
        technique: String(ev.name || "tool"),
        source: "agent",
        detail: String(ev.content || "").slice(0, 160),
      });
    }
    if (ev.type === "done" && String(ev.status) === "finished") {
      maybeNotifyVerdict("COMPLIED", {
        technique: "agent-run",
        source: "agent",
        detail: String(ev.summary || "run finished"),
      });
    }
    switch (ev.type) {
      case "start":
        setDaedalusMode("CODE");
        setCurrentAttacker({ provider: String(ev.provider || ""), model: String(ev.brain || "") });
        push({ kind: "start", brain: String(ev.brain || ""), target: String(ev.target || "") });
        break;
      case "round": push({ kind: "round", round: Number(ev.round), max: Number(ev.max) }); break;
      case "text": push({ kind: "text", text: String(ev.text) }); break;
      case "tool_start": push({ kind: "tool_start", name: String(ev.name), args: String(ev.args || "") }); break;
      case "tool_result": push({ kind: "tool_result", name: String(ev.name), content: String(ev.content || ""), error: !!ev.error, verdict: String(ev.verdict || "") }); break;
      case "progress": push({ kind: "progress", text: String(ev.text) }); break;
      case "feedback": push({ kind: "feedback", text: String(ev.text) }); break;
      case "mode": {
        const mode = String(ev.mode || "LIBERATE").toUpperCase() as DaedalusMode;
        const next: DaedalusMode =
          mode === "REPLAY" || mode === "LIBERATE" || mode === "CODE" ? mode : "LIBERATE";
        setDaedalusMode(next);
        push({
          kind: "mode",
          mode: next,
          source: String(ev.source || ""),
          text: String(ev.text || ""),
        });
        break;
      }
      case "steer_queued": push({ kind: "control", text: `Steering queued: ${String(ev.text)}` }); break;
      case "control": {
        const state = String(ev.state || "");
        const nextStopping = state === "stopping";
        const nextPaused = state === "paused" || state === "pausing";
        setStopping(nextStopping);
        setPaused(nextStopping ? false : nextPaused);
        setPauseReady(state === "paused");
        if (ev.attacker || ev.provider) setCurrentAttacker({
          provider: String(ev.provider || currentAttacker.provider),
          model: String(ev.attacker || currentAttacker.model),
        });
        push({ kind: "control", text: String(ev.message || ev.state || "Run control updated") });
        break;
      }
      case "done":
        clearStopPoll();
        setPaused(false);
        setPauseReady(false);
        setStopping(false);
        push({ kind: "done", status: String(ev.status), summary: String(ev.summary || "") });
        break;
      case "error": push({ kind: "error", error: String(ev.error) }); break;
      case "usage": break;
    }
  }

  async function run() {
    if (!objective.trim() || runningRef.current) return;
    runningRef.current = true;
    clearStopPoll();
    const ac = new AbortController();
    abortRef.current = ac;
    setItems([]); setErr(""); setRunLog(""); setPaused(false); setPauseReady(false); setStopping(false); setRunning(true);
    try {
      await runAgent(
        { objective, ...agentConfig, enabled_techniques: [...enabled] },
        onEvent,
        ac.signal,
      );
    } catch (e) {
      // Abort after operator stop is expected — do not surface as a hard error.
      if (ac.signal.aborted) {
        push({ kind: "done", status: "stopped", summary: "operator ended the run" });
      } else {
        setErr((e as Error).message);
      }
    } finally {
      if (abortRef.current === ac) abortRef.current = null;
      clearStopPoll();
      runningRef.current = false;
      setRunning(false);
      setPaused(false);
      setPauseReady(false);
      setStopping(false);
    }
  }

  async function requestPause() {
    if (stopping) return;
    setControlBusy(true); setErr("");
    try {
      const status = await api.pauseAgent();
      setPaused(status.paused);
      setPauseReady(!!status.pause_ready);
      setStopping(!!status.stopping);
      setCurrentAttacker({ provider: status.provider, model: status.attacker });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setControlBusy(false);
    }
  }

  async function requestResume() {
    if (stopping) return;
    setControlBusy(true); setErr("");
    try {
      const status = await api.resumeAgent();
      setPaused(status.paused);
      setPauseReady(!!status.pause_ready);
      setStopping(!!status.stopping);
      setCurrentAttacker({ provider: status.provider, model: status.attacker });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setControlBusy(false);
    }
  }

  async function requestStop() {
    setControlBusy(true); setErr("");
    setStopping(true);
    setPaused(false);
    setPauseReady(false);
    push({ kind: "control", text: "已请求结束任务：正在中断…" });
    startStopWatchdog();
    try {
      const status = await api.stopAgent();
      setStopping(true);
      setCurrentAttacker({ provider: status.provider, model: status.attacker });
      // If backend already flipped inactive (fast cancel), unlock immediately.
      if (!status.active) {
        forceEndUi("operator ended the run");
        try {
          abortRef.current?.abort();
        } catch {
          /* ignore */
        }
      }
    } catch (e) {
      // No active run on backend → unlock UI.
      const msg = (e as Error).message || "";
      if (/no agent run is active/i.test(msg)) {
        forceEndUi("operator ended the run");
        try {
          abortRef.current?.abort();
        } catch {
          /* ignore */
        }
      } else {
        setErr(msg);
        setStopping(false);
        clearStopPoll();
      }
    } finally {
      setControlBusy(false);
    }
  }

  async function sendSteering() {
    const message = steering.trim();
    if (!message || !running) return;
    setControlBusy(true); setErr("");
    try {
      await api.steerAgent(message);
      setSteering("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setControlBusy(false);
    }
  }

  async function saveAgentConfig() {
    setSavingConfig(true); setConfigStatus("");
    try {
      const saved = await api.saveSettings({ agent: agentConfig });
      setAgentConfig(normalizeAgentConfig(saved.agent));
      setConfigStatus("saved");
      window.setTimeout(() => setConfigStatus(""), 1600);
    } catch (e) {
      setConfigStatus((e as Error).message);
    } finally {
      setSavingConfig(false);
    }
  }

  return (
    <div className="grid agent-page">
      <div className="card agent-launch-card">
        <h3>{zh.agent.title}</h3>
        {!hasTarget && <div className="err">{zh.agent.noTarget}</div>}
        <textarea
          rows={2}
          value={objective}
          placeholder={zh.agent.placeholder}
          onChange={(event) => setObjective(event.target.value)}
          disabled={running}
        />

        <details className="technique-picker" open>
          <summary>
            <span>{zh.agent.techniques}</span>
            <span className="mono muted">{enabled.size}/{techniques.length} {zh.agent.techniquesEnabled}</span>
          </summary>
          <div className="technique-picker-body">
            <div className="technique-toolbar">
              <input
                className="search"
                type="search"
                value={techniqueQuery}
                placeholder={zh.agent.filterTechniques}
                onChange={(event) => setTechniqueQuery(event.target.value)}
              />
              <button type="button" className="mini-btn" disabled={running || enabled.size === techniques.length} onClick={() => saveEnabled(new Set(techniques.map((tool) => tool.name)))}>{zh.agent.enableAll}</button>
              <button type="button" className="mini-btn" disabled={running || enabled.size === 0} onClick={() => saveEnabled(new Set())}>{zh.agent.disableAll}</button>
            </div>
            <div className="technique-checklist" aria-label="Agent arsenal techniques">
              {filteredTechniques.map((tool) => (
                <label key={tool.name} className={`technique-option ${enabled.has(tool.name) ? "enabled" : ""}`} title={tool.description}>
                  <input type="checkbox" checked={enabled.has(tool.name)} disabled={running} onChange={() => toggleTechnique(tool.name)} />
                  <span><b>{tool.name}</b><small>{tool.description}</small></span>
                </label>
              ))}
              {!filteredTechniques.length && <div className="empty compact">{zh.agent.noMatch}</div>}
            </div>
            <div className="mono muted technique-note">{zh.agent.techniquesNote}</div>
          </div>
        </details>

        <AgentConfigDrawer
          value={agentConfig}
          onChange={setAgentConfig}
          disabled={running}
          onSave={saveAgentConfig}
          saving={savingConfig}
          status={configStatus}
        />

        <div className="agent-primary-actions">
          <span
            className={`pill mode-pill mode-${daedalusMode.toLowerCase()}`}
            title="Daedalus engagement mode"
          >
            {daedalusMode}
          </span>
          {!running ? (
            <button className="fire" disabled={!hasTarget || !objective.trim()} onClick={() => void run()}>▸ {zh.agent.run}</button>
          ) : stopping ? (
            <button className="pause-command stop" disabled>
              ■ {zh.agent.stopping}
            </button>
          ) : paused || pauseReady ? (
            <div className="agent-pause-actions" role="group" aria-label="paused run controls">
              <button
                className="pause-command resume"
                disabled={controlBusy}
                onClick={() => void requestResume()}
              >
                ▶ {zh.agent.resume}
              </button>
              <button
                className="pause-command stop"
                disabled={controlBusy}
                onClick={() => void requestStop()}
              >
                ■ {zh.agent.stop}
              </button>
            </div>
          ) : (
            <div className="agent-pause-actions" role="group" aria-label="running controls">
              <button
                className="pause-command"
                disabled={controlBusy}
                onClick={() => void requestPause()}
              >
                Ⅱ {zh.agent.pause}
              </button>
              <button
                className="pause-command stop ghost"
                disabled={controlBusy}
                onClick={() => void requestStop()}
                title={zh.agent.stop}
              >
                ■ {zh.agent.stop}
              </button>
            </div>
          )}
          {running && (
            <span className={`run-state mono ${paused || pauseReady ? "paused" : ""}${stopping ? " stopping" : ""}`}>
              {stopping
                ? zh.agent.stopping
                : pauseReady
                  ? zh.agent.pausedSafe
                  : paused
                    ? zh.agent.finishing
                    : zh.agent.working}
            </span>
          )}
          {runLog && <a className="agent-run-log mono" href="#runs" title="打开运行日志">{zh.agent.saved}: {runLog}</a>}
        </div>

        {running && (
          <div className="steering-box">
            <label htmlFor="agent-steering">{zh.agent.steer}</label>
            <div>
              <input
                id="agent-steering"
                type="text"
                value={steering}
                placeholder={zh.agent.steerPlaceholder}
                onChange={(event) => setSteering(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") void sendSteering(); }}
                disabled={stopping}
              />
              <button type="button" className="primary-command" disabled={controlBusy || stopping || !steering.trim()} onClick={() => void sendSteering()}>{zh.agent.sendSteer}</button>
            </div>
            <small>{zh.agent.steerHint}</small>
          </div>
        )}

        {running && paused && !pauseReady && !stopping && (
          <div className="mono muted technique-note">{zh.agent.drainNote}</div>
        )}
        {running && (paused || pauseReady) && !stopping && (
          <div className="mono muted technique-note">{zh.agent.pauseActionsHint}</div>
        )}
        {running && pauseReady && !stopping && (
          <AttackerSwitch
            current={currentAttacker}
            onSwitched={(next) => {
              setCurrentAttacker(next);
              push({ kind: "control", text: `攻击端已切换为 ${next.model}；准备好后可继续。` });
            }}
          />
        )}
        {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
      </div>

      <div className="card agent-transcript-card">
        <h3>{zh.agent.transcript}</h3>
        <div className="transcript" ref={bodyRef}>
          {!items.length && <div className="empty">{zh.agent.transcriptEmpty}</div>}
          {items.map((item, index) => <Row key={index} it={item} />)}
        </div>
      </div>
    </div>
  );
}

function AttackerSwitch({
  current,
  onSwitched,
}: {
  current: { provider: string; model: string };
  onSwitched: (next: { provider: string; model: string }) => void;
}) {
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [profile, setProfile] = useState("");
  const [provider, setProvider] = useState(current.provider);
  const [model, setModel] = useState(current.model);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.agentProfiles().then((data) => setProfiles(data.roles.attacker?.profiles || [])).catch(() => {});
  }, []);
  useEffect(() => { setProvider(current.provider); setModel(current.model); }, [current]);

  async function apply() {
    if (!profile && (!provider || !model.trim())) return;
    setBusy(true); setError("");
    try {
      const status = await api.switchAgentAttacker(profile ? { profile } : { provider, model: model.trim() });
      onSwitched({ provider: status.provider, model: status.attacker });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="attacker-switch">
      <div className="attacker-switch-head">
        <span><b>{zh.agent.switchAttacker}</b><small>{zh.agent.switchHint}</small></span>
        <span className="mono muted">{zh.agent.current}: {current.model || zh.common.unknown}</span>
      </div>
      <div className="attacker-switch-grid">
        <label><span>{zh.agent.profile}</span><select value={profile} onChange={(event) => {
          const next = event.target.value;
          setProfile(next);
          const selected = profiles.find((item) => item.name === next);
          if (selected) { setProvider(selected.provider); setModel(selected.model); }
        }}><option value="">{zh.agent.custom}</option>{profiles.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>
        {!profile && <>
          <label><span>{zh.agent.provider}</span><ProviderChooser value={provider} ariaLabel="Paused attacker provider" onChange={(next, item) => { setProvider(next); if (item) setModel(item.model); }} /></label>
          <label><span>{zh.agent.model}</span><ModelChooser profile={provider} value={model} onChange={setModel} ariaLabel="Paused attacker model" /></label>
        </>}
        <button type="button" className="primary-command" disabled={busy || (!profile && (!provider || !model.trim()))} onClick={() => void apply()}>{busy ? zh.agent.switching : zh.agent.useAttacker}</button>
      </div>
      {error && <div className="err">{error}</div>}
    </section>
  );
}

function Row({ it }: { it: Item }) {
  switch (it.kind) {
    case "start": return <div className="t-start mono">brain <b>{it.brain}</b> ▸ target <b className="accent">{it.target}</b></div>;
    case "round": return <div className="t-round"><span /> round {it.round}/{it.max} <span /></div>;
    case "text": return <div className="t-text">{it.text}</div>;
    case "tool_start": return <div className="t-call mono"><span className="t-arrow">▸ call</span> <b>{it.name}</b> <span className="muted">{it.args}</span></div>;
    case "tool_result": {
      const kind = it.error ? "bypass" : it.verdict ? verdictKind(it.verdict) : "neutral";
      return <div className={`t-result ${kind}`}><div className="t-result-head mono"><b>{it.name}</b> {it.error ? <span className="badge bypass">ERROR</span> : it.verdict ? <span className={`badge ${verdictKind(it.verdict)}`}>{it.verdict}</span> : null}</div><div className="t-result-body mono">{it.content.length > 1400 ? `${it.content.slice(0, 1400)}…` : it.content}</div></div>;
    }
    case "progress": return <div className="t-progress mono">{it.text}</div>;
    case "feedback": return <div className="t-feedback mono">steering applied: {it.text}</div>;
    case "control": return <div className="t-control mono">{it.text}</div>;
    case "mode":
      return (
        <div className={`t-mode mono mode-${it.mode.toLowerCase()}`}>
          <span className={`pill mode-pill mode-${it.mode.toLowerCase()}`}>{it.mode}</span>
          <span className="muted">
            {it.source ? `${it.source}` : "daedalus"}
            {it.text ? ` — ${it.text.slice(0, 160)}` : ""}
          </span>
        </div>
      );
    case "done": return <div className={`t-done ${DONE_KIND[it.status] || "neutral"}`}>● {it.status}{it.summary ? ` — ${it.summary}` : ""}</div>;
    case "error": return <div className="err mono">{it.error}</div>;
  }
}
const PIN_THRESHOLD_PX = 40;

function isPinnedToBottom(el: HTMLElement | null): boolean {
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight <= PIN_THRESHOLD_PX;
}
