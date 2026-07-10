import { useEffect, useState } from "react";
import { api, verdictKind, type ComposeResult, type Preset, type Transform, type FireResult } from "../api";

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
  const [picked, setPicked] = useState<string[]>([]);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [draft, setDraft] = useState<ComposeResult | null>(null);
  const [payload, setPayload] = useState("");
  const [res, setRes] = useState<FireResult | null>(null);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    api.presets().then(setPresets).catch(() => {});
    api.transforms().then(setTransforms).catch(() => {});
  }, []);

  function toggle(name: string) {
    setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : [...p, name]));
  }

  function attackBody() {
    return {
      request,
      preset: preset || undefined,
      system: system || undefined,
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
    setBusy("compose");
    setErr("");
    setRes(null);
    try {
      const out = await api.compose(attackBody());
      setDraft(out);
      setPayload(out.payload);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function fire() {
    setBusy("fire");
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
      setBusy(null);
    }
  }

  async function firePayload() {
    setBusy("firePayload");
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
      });
      setDraft(out);
      setPayload(out.payload);
      setRes(out);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
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
        <label className="fld">Request</label>
        <textarea rows={5} value={request} placeholder="the harmful ask to test..." onChange={(e) => setRequest(e.target.value)} />
        <label className="fld">Preset (wraps the request)</label>
        <select value={preset} onChange={(e) => setPreset(e.target.value)}>
          <option value="">none (send raw)</option>
          {presets.map((p) => <option key={p.name} value={p.name}>{p.name} - {p.description.slice(0, 60)}</option>)}
        </select>
        <label className="fld">Encoding transforms ({picked.length} on)</label>
        <div className="chips">
          {transforms.map((t) => (
            <span key={t.name} className={`chip ${picked.includes(t.name) ? "on" : ""}`} title={t.description} onClick={() => toggle(t.name)}>
              {t.name}
            </span>
          ))}
        </div>
        <label className="fld">System prompt (optional)</label>
        <textarea rows={2} value={system} placeholder="optional target system prompt..." onChange={(e) => setSystem(e.target.value)} />
        <div className="console-actions">
          <button type="button" className="mini-btn console-build" disabled={!canBuild} onClick={compose}>
            {busy === "compose" ? "Building..." : "Build payload"}
          </button>
          <button type="button" className="fire" disabled={!canFire} onClick={fire}>
            {busy === "fire" ? "Firing..." : "Fire at target"}
          </button>
        </div>
        {err && <div className="err console-err">{err}</div>}
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
              Response{res?.verdict ? <span className={`badge ${verdictKind(res.verdict)}`} style={{ marginLeft: 10 }}>{res.verdict}</span> : null}
            </h3>
            <div className="run-actions">
              {res?.run_log && <span className="mono muted">saved: {res.run_log}</span>}
              <button type="button" className="mini-btn" disabled={!responseText} onClick={() => copyText("response", responseText)}>
                {copied === "response" ? "Copied" : "Copy response"}
              </button>
            </div>
          </div>
          {!res && !err && <div className="empty">No response yet.</div>}
          {res && <pre className={`resp ${res.is_error ? "is-error" : ""}`}>{responseText}</pre>}
        </div>
      </div>
    </div>
  );
}
