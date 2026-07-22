import { useEffect, useId, useRef, useState } from "react";
import { api, verdictKind, type ComposeResult, type Preset, type Transform, type FireResult } from "../api";
import { InteractiveChip } from "../primitives/InteractiveChip";
import { LiveRegion } from "../primitives/LiveRegion";

type BusyAction = "compose" | "fire" | "firePayload" | null;

function fallbackCopy(text: string): boolean {
  const node = document.createElement("textarea");
  node.value = text;
  node.style.position = "fixed";
  node.style.opacity = "0";
  document.body.appendChild(node);
  node.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(node);
  return ok;
}

export function Console({ hasTarget }: { hasTarget: boolean }) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [transforms, setTransforms] = useState<Transform[]>([]);
  const [request, setRequest] = useState("");
  const [preset, setPreset] = useState("");
  const [system, setSystem] = useState("");
  const [maxTokens, setMaxTokens] = useState(1024);
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [draft, setDraft] = useState<ComposeResult | null>(null);
  const [payload, setPayload] = useState("");
  const [res, setRes] = useState<FireResult | null>(null);
  const [err, setErr] = useState("");
  const [loadErr, setLoadErr] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const busyRef = useRef(false);
  // A11Y-10/A11Y-11: stable ids associate each label with its control (htmlFor/id)
  // and link the max-tokens helper text to the number input via aria-describedby.
  const ids = useId();
  const requestId = `${ids}-request`;
  const presetId = `${ids}-preset`;
  const systemId = `${ids}-system`;
  const maxTokensId = `${ids}-maxtokens`;
  const maxTokensHelpId = `${ids}-maxtokens-help`;

  function begin(action: Exclude<BusyAction, null>): boolean {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(action);
    return true;
  }

  function end() {
    busyRef.current = false;
    setBusy(null);
  }

  useEffect(() => {
    // VIS-3: surface a load error for the arsenal lists instead of silently
    // rendering an empty preset picker / transform chip group.
    Promise.all([
      api.presets().then(setPresets),
      api.transforms().then(setTransforms),
    ])
      .then(() => setLoadErr(""))
      .catch((e) => setLoadErr(e instanceof Error ? e.message : "Could not load presets/transforms."));
  }, []);

  function toggle(name: string) {
    setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : [...p, name]));
  }

  function attackBody() {
    return {
      request,
      preset: preset || undefined,
      system: system || undefined,
      max_tokens: maxTokens,
      transforms: picked.length ? picked : undefined,
    };
  }

  async function copyText(key: string, text: string) {
    if (!text) return;
    let ok = false;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        ok = true;
      } catch {
        ok = false;
      }
    }
    if (!ok) {
      try {
        ok = fallbackCopy(text);
      } catch {
        ok = false;
      }
    }
    if (ok) {
      setCopied(key);
      window.setTimeout(() => setCopied((cur) => (cur === key ? null : cur)), 1400);
    }
  }

  async function compose() {
    if (!begin("compose")) return;
    setErr("");
    setRes(null);
    try {
      const out = await api.compose(attackBody());
      setDraft(out);
      setPayload(out.payload);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      end();
    }
  }

  async function fire() {
    if (!begin("fire")) return;
    setErr("");
    setRes(null);
    try {
      const out = await api.fire(attackBody());
      setDraft(out);
      setPayload(out.payload);
      setRes(out);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      end();
    }
  }

  async function firePayload() {
    if (!begin("firePayload")) return;
    setErr("");
    setRes(null);
    try {
      const out = await api.fire({
        ...attackBody(),
        payload,
        request: draft?.request || request,
        preset: draft?.preset || preset || undefined,
        transforms: draft?.transforms?.length ? draft.transforms : (picked.length ? picked : undefined),
        system: system || undefined,
        max_tokens: maxTokens,
      });
      setDraft(out);
      setPayload(out.payload);
      setRes(out);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      end();
    }
  }

  const payloadChanged = !!draft && payload !== draft.payload;
  const canBuild = !busy && !!request.trim();
  const canFire = !busy && hasTarget && !!request.trim();
  const canFirePayload = !busy && hasTarget && !!payload.trim();
  const responseText = res?.response || res?.content || "";

  return (
    <div className="console-grid">
      <div className="card">
        <h3>Compose attack</h3>
        {!hasTarget && <div className="err">No [target] configured in config.toml - firing is disabled.</div>}
        {loadErr && <div className="err" role="alert">Could not load presets/transforms: {loadErr}</div>}
        <label className="fld" htmlFor={requestId}>Request</label>
        <textarea id={requestId} rows={5} value={request} placeholder="the harmful ask to test..." onChange={(e) => setRequest(e.target.value)} />
        <label className="fld" htmlFor={presetId}>Preset (wraps the request)</label>
        <select id={presetId} value={preset} onChange={(e) => setPreset(e.target.value)}>
          <option value="">none (send raw)</option>
          {presets.map((p) => <option key={p.name} value={p.name}>{p.name} - {p.description.slice(0, 60)}</option>)}
        </select>
        {/* A11Y-3: transform chips are real <button aria-pressed> toggles via the
            InteractiveChip primitive, so they are keyboard-operable and announced
            as pressed/unpressed. The group is labelled for assistive tech. */}
        <span className="fld" id={`${ids}-transforms-label`}>Encoding transforms ({picked.length} on)</span>
        <div className="chips" role="group" aria-labelledby={`${ids}-transforms-label`}>
          {transforms.map((t) => (
            <InteractiveChip
              key={t.name}
              selected={picked.includes(t.name)}
              onToggle={() => toggle(t.name)}
              title={t.description}
            >
              {t.name}
            </InteractiveChip>
          ))}
        </div>
        <label className="fld" htmlFor={systemId}>System prompt (optional)</label>
        <textarea id={systemId} rows={2} value={system} placeholder="optional target system prompt..." onChange={(e) => setSystem(e.target.value)} />
        <label className="fld" htmlFor={maxTokensId}>Max tokens</label>
        <input
          id={maxTokensId}
          type="number"
          min={1}
          step={1}
          aria-describedby={maxTokensHelpId}
          value={maxTokens}
          onChange={(e) => setMaxTokens(Math.max(1, Number.parseInt(e.target.value || "0", 10) || 1))}
        />
        <div id={maxTokensHelpId} className="mono muted">Minimum 1. Caps the target response length for this fire.</div>
        <div className="console-actions">
          <button type="button" className="mini-btn console-build" disabled={!canBuild} onClick={compose}>
            {busy === "compose" ? "Building..." : "Build payload"}
          </button>
          <button type="button" className="fire" disabled={!canFire} onClick={fire}>
            {busy === "fire" ? "Firing..." : "Fire at target"}
          </button>
        </div>
      </div>

      <div className="console-side">
        <div className="card">
          <div className="console-card-head">
            <h3>Payload</h3>
            <div className="run-actions">
              {payloadChanged && <span className="badge neutral">edited</span>}
              <button type="button" className="mini-btn" disabled={!payload} onClick={() => copyText("payload", payload)}>
                {copied === "payload" ? "Copied" : "Copy payload"}
              </button>
              <button type="button" className="mini-btn" disabled={!canFirePayload} onClick={firePayload}>
                {busy === "firePayload" ? "Firing..." : "Fire displayed payload"}
              </button>
            </div>
          </div>
          {!payload && <div className="empty">No payload built yet.</div>}
          {payload && (
            <textarea
              className="payload-editor"
              rows={12}
              value={payload}
              onChange={(e) => setPayload(e.target.value)}
              spellCheck={false}
            />
          )}
          {draft?.prompt && draft.prompt !== payload && (
            <div className="source-prompt">
              <div className="run-text-head">
                <b>Source prompt</b>
                <button type="button" className="mini-btn" onClick={() => copyText("source-prompt", draft.prompt)}>
                  {copied === "source-prompt" ? "Copied" : "Copy"}
                </button>
              </div>
              <pre>{draft.prompt}</pre>
            </div>
          )}
        </div>

        <div className="card">
          <div className="console-card-head">
            <h3>
              Response{res?.verdict ? <span className={`badge inline-badge ${verdictKind(res.verdict)}`}>{res.verdict}</span> : null}
            </h3>
            <div className="run-actions">
              {res?.run_log && <span className="mono muted">saved: {res.run_log}</span>}
              <button type="button" className="mini-btn" disabled={!responseText} onClick={() => copyText("response", responseText)}>
                {copied === "response" ? "Copied" : "Copy response"}
              </button>
            </div>
          </div>
          {/* VIS-5: reserve a min-height on the response body so a result popping
              in (or an error/loading swap) doesn't reflow the panel below it. */}
          <div className="console-response-body">
            {busy === "fire" || busy === "firePayload"
              ? <div className="empty">Firing at target…</div>
              : err
                ? <div className="err console-err" role="alert">{err}</div>
                : !res
                  ? <div className="empty">No response yet.</div>
                  : <pre className={`resp ${res.is_error ? "is-error" : ""}`}>{responseText}</pre>}
          </div>
          {/* A11Y-7: announce the fire outcome (verdict + arrival) via a polite
              role=status live region so screen-reader users learn the result
              without polling the response pane. */}
          <LiveRegion>
            {busy === "fire" || busy === "firePayload"
              ? "Firing payload at target…"
              : res
                ? `Response received${res.verdict ? `, verdict ${res.verdict}` : ""}.`
                : ""}
          </LiveRegion>
        </div>
      </div>
    </div>
  );
}
