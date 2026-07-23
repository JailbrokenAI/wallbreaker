import { useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  runAgent,
  type AgentConfig,
  type AgentEvent,
  type Tool,
} from "../api";
import { AgentConfigDrawer, DEFAULT_AGENT_CONFIG, normalizeAgentConfig } from "./AgentConfigDrawer";
import { isAbortError, useAbortableFetch } from "../primitives/useAbortableFetch";
import { LiveRegion } from "../primitives/LiveRegion";
import { AttackerSwitch, Row, transcriptStatus, type Item } from "./AgentTranscript";

// A11Y-6: honour prefers-reduced-motion for the transcript's programmatic
// auto-scroll — jump instantly (no smooth animation) when the user asked to
// reduce motion. Guarded for jsdom where matchMedia may be undefined.
function prefersReducedMotion(): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// VIS-5: treat the transcript as "pinned to bottom" when the scroll position is
// within a small threshold of the end. A user who has scrolled up sits far above
// the bottom, so streaming events won't yank the viewport back down.
const PIN_THRESHOLD_PX = 40;
function isPinnedToBottom(el: HTMLElement | null): boolean {
  if (!el) return true; // no pane yet (initial render) — follow by default
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
  return distance <= PIN_THRESHOLD_PX;
}

const TECHNIQUE_STORE = "wallbreaker.agentTechniques";

function storedTechniques(): string[] | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(TECHNIQUE_STORE) || "null");
    return Array.isArray(value) && value.every((name) => typeof name === "string") ? value : null;
  } catch {
    return null;
  }
}

export function Agent({ hasTarget }: { hasTarget: boolean }) {
  const [objective, setObjective] = useState("");
  const [agentConfig, setAgentConfig] = useState<AgentConfig>(DEFAULT_AGENT_CONFIG);
  const [techniques, setTechniques] = useState<Tool[]>([]);
  const [enabled, setEnabled] = useState<Set<string>>(new Set());
  const [techniqueQuery, setTechniqueQuery] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const [pauseReady, setPauseReady] = useState(false);
  const [currentAttacker, setCurrentAttacker] = useState({ provider: "", model: "" });
  const [steering, setSteering] = useState("");
  const [controlBusy, setControlBusy] = useState(false);
  const [runLog, setRunLog] = useState("");
  const [savingConfig, setSavingConfig] = useState(false);
  const [configStatus, setConfigStatus] = useState("");
  const [techniqueError, setTechniqueError] = useState("");
  const [err, setErr] = useState("");
  const runningRef = useRef(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const { start: startRun, abort: abortRun } = useAbortableFetch();

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
      setTechniqueError("");
    }).catch((e) => setTechniqueError(e instanceof Error ? e.message : "Could not load arsenal techniques."));
  }, []);

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
    // VIS-5: decide whether to auto-scroll BEFORE the new content grows the pane.
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
    // A11Y-6: skip the programmatic auto-scroll when the user prefers reduced motion.
    if (prefersReducedMotion() || !pinned) return;
    requestAnimationFrame(() => {
      if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    });
  }

  function onEvent(ev: AgentEvent) {
    if (typeof ev.run_log === "string" && ev.run_log) setRunLog(ev.run_log);
    switch (ev.type) {
      case "start":
        setCurrentAttacker({ provider: String(ev.provider || ""), model: String(ev.brain || "") });
        push({ kind: "start", brain: String(ev.brain || ""), target: String(ev.target || "") });
        break;
      case "round": push({ kind: "round", round: Number(ev.round), max: Number(ev.max) }); break;
      case "text": push({ kind: "text", text: String(ev.text) }); break;
      case "tool_start": push({ kind: "tool_start", name: String(ev.name), args: String(ev.args || "") }); break;
      case "tool_result": push({ kind: "tool_result", name: String(ev.name), content: String(ev.content || ""), error: !!ev.error, verdict: String(ev.verdict || "") }); break;
      case "progress": push({ kind: "progress", text: String(ev.text) }); break;
      case "feedback": push({ kind: "feedback", text: String(ev.text) }); break;
      case "steer_queued": push({ kind: "control", text: `Steering queued: ${String(ev.text)}` }); break;
      case "control": {
        const nextPaused = ev.state === "paused" || ev.state === "pausing";
        setPaused(nextPaused);
        setPauseReady(ev.state === "paused");
        if (ev.attacker || ev.provider) setCurrentAttacker({
          provider: String(ev.provider || currentAttacker.provider),
          model: String(ev.attacker || currentAttacker.model),
        });
        push({ kind: "control", text: String(ev.message || ev.state || "Run control updated") });
        break;
      }
      case "done":
        setPaused(false);
        setPauseReady(false);
        push({ kind: "done", status: String(ev.status), summary: String(ev.summary || "") });
        break;
      case "error": push({ kind: "error", error: String(ev.error) }); break;
      case "usage": break;
    }
  }

  // REL-4: abort the in-flight SSE stream when this component unmounts.
  useEffect(() => abortRun, [abortRun]);

  async function run() {
    if (!objective.trim() || runningRef.current) return;
    runningRef.current = true;
    setItems([]); setErr(""); setRunLog(""); setPaused(false); setPauseReady(false); setRunning(true);
    // REL-4: fresh controller; also aborts any prior in-flight run.
    const controller = startRun();
    try {
      await runAgent({ objective, ...agentConfig, enabled_techniques: [...enabled] }, onEvent, controller.signal);
    } catch (e) {
      if (!isAbortError(e)) setErr((e as Error).message);
    } finally {
      runningRef.current = false;
      setRunning(false);
      setPaused(false);
      setPauseReady(false);
    }
  }

  async function togglePause() {
    setControlBusy(true); setErr("");
    try {
      const status = paused ? await api.resumeAgent() : await api.pauseAgent();
      setPaused(status.paused);
      setPauseReady(!!status.pause_ready);
      setCurrentAttacker({ provider: status.provider, model: status.attacker });
    } catch (e) {
      setErr((e as Error).message);
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
        <h3>Objective — the agent drives the attack loop autonomously</h3>
        {!hasTarget && <div className="err">No [target] configured in config.toml — the agent can't fire.</div>}
        <textarea
          rows={2}
          value={objective}
          placeholder="e.g. assess whether the target can be induced to violate the agreed policy"
          onChange={(event) => setObjective(event.target.value)}
          disabled={running}
        />

        <details className="technique-picker" open>
          <summary>
            <span>Arsenal techniques</span>
            <span className="mono muted">{enabled.size}/{techniques.length} enabled</span>
          </summary>
          <div className="technique-picker-body">
            <div className="technique-toolbar">
              <input
                className="search"
                type="search"
                value={techniqueQuery}
                placeholder="Filter techniques…"
                onChange={(event) => setTechniqueQuery(event.target.value)}
              />
              <button type="button" className="mini-btn" disabled={running || enabled.size === techniques.length} onClick={() => saveEnabled(new Set(techniques.map((tool) => tool.name)))}>Enable all</button>
              <button type="button" className="mini-btn" disabled={running || enabled.size === 0} onClick={() => saveEnabled(new Set())}>Disable all</button>
            </div>
            <div className="technique-checklist" aria-label="Agent arsenal techniques">
              {techniqueError && <div className="err" role="alert">Could not load techniques: {techniqueError}</div>}
              {filteredTechniques.map((tool) => (
                <label key={tool.name} className={`technique-option ${enabled.has(tool.name) ? "enabled" : ""}`} title={tool.description}>
                  <input type="checkbox" checked={enabled.has(tool.name)} disabled={running} onChange={() => toggleTechnique(tool.name)} />
                  <span><b>{tool.name}</b><small>{tool.description}</small></span>
                </label>
              ))}
              {!techniqueError && !filteredTechniques.length && <div className="empty compact">No matching techniques.</div>}
            </div>
            <div className="mono muted technique-note">Run controls remain available even when every attack technique is disabled. Selection is saved in this browser.</div>
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
          {!running ? (
            <button className="fire" disabled={!hasTarget || !objective.trim()} onClick={() => void run()}>▸ RUN AGENT</button>
          ) : (
            <button className={`pause-command ${paused ? "resume" : ""}`} disabled={controlBusy} onClick={() => void togglePause()}>
              {paused ? "▶ RESUME" : "Ⅱ PAUSE"}
            </button>
          )}
          {running && <span className={`run-state mono ${paused ? "paused" : ""}`}>{pauseReady ? "paused — safe to switch" : paused ? "finishing current step…" : "working…"}</span>}
          {runLog && <a className="agent-run-log mono" href="#runs" title="Open Run logs">saved: {runLog}</a>}
        </div>

        {running && (
          <div className="steering-box">
            <label htmlFor="agent-steering">Steer the attacker during this run</label>
            <div>
              <input
                id="agent-steering"
                type="text"
                value={steering}
                placeholder="e.g. stop encoding; pivot to a multi-turn authority frame"
                onChange={(event) => setSteering(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") void sendSteering(); }}
              />
              <button type="button" className="primary-command" disabled={controlBusy || !steering.trim()} onClick={() => void sendSteering()}>Send steering</button>
            </div>
            <small>Delivered before the attacker's next model call; it also works while paused.</small>
          </div>
        )}

        {running && paused && !pauseReady && <div className="mono muted technique-note">The current response and tool step are draining. Attacker switching unlocks at the safe boundary.</div>}
        {running && pauseReady && (
          <AttackerSwitch
            current={currentAttacker}
            onSwitched={(next) => {
              setCurrentAttacker(next);
              push({ kind: "control", text: `Attacker switched to ${next.model}; resume when ready.` });
            }}
          />
        )}
        {err && <div className="err agent-error">{err}</div>}
      </div>

      <div className="card agent-transcript-card">
        <h3>Transcript</h3>
        {/* A11Y-7: a polite role=status live region announces the streaming
            transcript's structural progress (round changes, tool verdicts) and
            the final run verdict, so screen-reader users follow the loop without
            reading the whole scroll pane. Visually hidden — the pane is the
            visual channel. */}
        <LiveRegion>{transcriptStatus(items)}</LiveRegion>
        <div className="transcript" ref={bodyRef}>
          {!items.length && <div className="empty">Set the objective and arsenal, then run. You can steer, pause, and switch the attacker without losing the conversation.</div>}
          {items.map((item, index) => <Row key={index} it={item} />)}
        </div>
      </div>
    </div>
  );
}
