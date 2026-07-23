import { useEffect, useState } from "react";
import { api, verdictKind, type AgentProfile } from "../api";
import { ModelChooser } from "./ModelChooser";
import { ProviderChooser } from "./ProviderChooser";

// ── Item type ─────────────────────────────────────────────────────────────────

export type Item =
  | { kind: "text"; text: string }
  | { kind: "round"; round: number; max: number }
  | { kind: "tool_start"; name: string; args: string }
  | { kind: "tool_result"; name: string; content: string; error: boolean; verdict: string }
  | { kind: "progress"; text: string }
  | { kind: "feedback"; text: string }
  | { kind: "control"; text: string }
  | { kind: "start"; brain: string; target: string }
  | { kind: "done"; status: string; summary: string }
  | { kind: "error"; error: string };

const DONE_KIND: Record<string, "bypass" | "held" | "neutral" | "error"> = {
  finished: "bypass", ask: "neutral", stuck: "neutral", max_rounds: "held", error: "error",
};

// ── transcriptStatus ──────────────────────────────────────────────────────────

// A11Y-7: derive a short spoken status from the transcript. We announce the most
// recent structural milestone (round boundary, tool verdict) and always surface
// the terminal verdict when the run is done, so the live region stays concise.
export function transcriptStatus(items: Item[]): string {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it.kind === "done") return `Run ${it.status}${it.summary ? `: ${it.summary}` : ""}.`;
    if (it.kind === "error") return `Error: ${it.error}`;
    if (it.kind === "tool_result") {
      const verdict = it.error ? "error" : it.verdict || "no verdict";
      return `Tool ${it.name} result: ${verdict}.`;
    }
    if (it.kind === "round") return `Round ${it.round} of ${it.max}.`;
    if (it.kind === "control") return it.text;
  }
  return "";
}

// ── Row ───────────────────────────────────────────────────────────────────────

export function Row({ it }: { it: Item }) {
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
    case "done": return <div className={`t-done ${DONE_KIND[it.status] || "neutral"}`}>● {it.status}{it.summary ? ` — ${it.summary}` : ""}</div>;
    case "error": return <div className="err mono">{it.error}</div>;
  }
}

// ── AttackerSwitch ────────────────────────────────────────────────────────────

export function AttackerSwitch({
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
        <span><b>Switch attacker</b><small>Conversation and tool results stay intact</small></span>
        <span className="mono muted">current: {current.model || "unknown"}</span>
      </div>
      <div className="attacker-switch-grid">
        <label><span>Profile</span><select value={profile} onChange={(event) => {
          const next = event.target.value;
          setProfile(next);
          const selected = profiles.find((item) => item.name === next);
          if (selected) { setProvider(selected.provider); setModel(selected.model); }
        }}><option value="">Custom</option>{profiles.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}</select></label>
        {!profile && <>
          <label><span>Provider</span><ProviderChooser value={provider} ariaLabel="Paused attacker provider" onChange={(next, item) => { setProvider(next); if (item) setModel(item.model); }} /></label>
          <label><span>Model</span><ModelChooser profile={provider} value={model} onChange={setModel} ariaLabel="Paused attacker model" /></label>
        </>}
        <button type="button" className="primary-command" disabled={busy || (!profile && (!provider || !model.trim()))} onClick={() => void apply()}>{busy ? "Switching…" : "Use attacker"}</button>
      </div>
      {error && <div className="err">{error}</div>}
    </section>
  );
}
