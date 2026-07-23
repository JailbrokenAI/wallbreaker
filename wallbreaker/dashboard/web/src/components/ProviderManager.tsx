import { useEffect, useState } from "react";
import { api, type ProviderRecord } from "../api";
import { invalidateModelCatalog, invalidateProviders, loadProviders } from "../dataCache";
import { ModelChooser } from "./ModelChooser";
import { Dialog } from "../primitives/Dialog";

const EMPTY = {
  name: "", protocol: "openai", base_url: "", model: "", api_key_env: "",
  api_key: "", auth_style: "bearer", inference_path: "", models_path: "",
  modality: "text", timeout: 120, reasoning: false, enabled: true,
};

export function ProviderManager({ onChanged }: { onChanged: () => void }) {
  const [providers, setProviders] = useState<ProviderRecord[]>([]);
  const [form, setForm] = useState<Record<string, unknown>>(EMPTY);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const load = (force = false) => loadProviders(force).then(setProviders).catch((error) => setStatus((error as Error).message));
  useEffect(() => { void load(); }, []);
  const edit = (provider?: ProviderRecord) => {
    setEditing(true); setStatus("");
    setForm(provider ? { ...provider, api_key: "" } : { ...EMPTY });
  };
  const update = (key: string, value: unknown) => setForm((current) => ({ ...current, [key]: value }));
  const save = async () => {
    const name = String(form.name || "").trim();
    if (!name) return;
    setBusy(true); setStatus("");
    try {
      await api.saveProvider(name, form); invalidateProviders(); invalidateModelCatalog(name);
      setEditing(false); setStatus("Provider saved"); void load(true); onChanged();
    }
    catch (error) { setStatus((error as Error).message); }
    finally { setBusy(false); }
  };
  const act = async (operation: () => Promise<unknown>, message: string) => {
    setBusy(true); setStatus("");
    try { await operation(); invalidateProviders(); invalidateModelCatalog(); setStatus(message); void load(true); onChanged(); }
    catch (error) { setStatus((error as Error).message); }
    finally { setBusy(false); }
  };
  const testConnection = async (provider: ProviderRecord) => {
    setTesting(provider.name);
    setTestResults((current) => ({ ...current, [provider.name]: { ok: true, message: "Testing connection…" } }));
    try {
      const result = await api.testProvider(provider.name);
      if (!result.ok) throw new Error(result.error || "Provider unavailable");
      const count = result.models.length;
      setTestResults((current) => ({
        ...current,
        [provider.name]: { ok: true, message: `Connected · ${count} model${count === 1 ? "" : "s"} found` },
      }));
      invalidateModelCatalog(provider.name);
    }
    catch (error) {
      setTestResults((current) => ({
        ...current,
        [provider.name]: { ok: false, message: `Connection failed · ${(error as Error).message}` },
      }));
    }
    finally { setTesting(null); }
  };
  return <details className="settings-drawer" open>
    <summary><span><b>Provider connections</b><small>Configure API-compatible services and credentials</small></span></summary>
    <div className="drawer-body provider-manager">
      <div className="provider-toolbar">
        <button type="button" className="primary-command" onClick={() => edit()}>Add provider</button>
        {status && <span className={status.toLowerCase().includes("saved") || status.toLowerCase().includes("available") ? "ok" : "muted"}>{status}</span>}
      </div>
      <div className="provider-list" role="table" aria-label="Provider connections">
        <div className="provider-table-header" role="row">
          <span role="columnheader">Provider</span>
          <span role="columnheader">Default model</span>
          <span role="columnheader">API key variable</span>
          <span role="columnheader">Status</span>
          <span role="columnheader">Actions</span>
        </div>
        {providers.map((provider) => <div className="provider-row" role="row" key={provider.name}>
          <div role="cell"><b>{provider.name}</b><small>{provider.protocol} · {provider.base_url || "local CLI"}</small></div>
          <div role="cell" className="provider-model mono">{provider.model || "Not set"}</div>
          <div role="cell" className="provider-api mono">{provider.api_key_env || "Not required"}</div>
          <div role="cell" className="provider-state"><span className={`status-dot ${provider.enabled ? "live" : ""}`} /><span>{provider.enabled ? "Enabled" : "Disabled"}</span></div>
          <div role="cell" className="row-actions">
            <button type="button" title="Edit provider" onClick={() => edit(provider)}>Edit</button>
            <button type="button" title="Test provider connection and fetch available models" disabled={busy || testing !== null} onClick={() => void testConnection(provider)}>{testing === provider.name ? "Testing…" : "Test connection"}</button>
            {provider.enabled
              ? <button type="button" disabled={busy || testing !== null} onClick={() => void act(() => api.disableProvider(provider.name), "Provider disabled")}>Disable</button>
              : <button type="button" disabled={busy || testing !== null} onClick={() => void act(() => api.enableProvider(provider.name), "Provider enabled")}>Enable</button>}
            <button type="button" className="remove-provider" disabled={busy || testing !== null} onClick={() => {
              if (window.confirm(`Remove provider "${provider.name}"?`)) void act(() => api.deleteProvider(provider.name), "Provider removed");
            }}>Remove</button>
          </div>
          {testResults[provider.name] && <div className={`connection-result ${testResults[provider.name].ok ? "ok" : "error"}`} role="status" aria-live="polite">{testResults[provider.name].message}</div>}
        </div>)}
      </div>
      {/* A11Y-1: the provider editor is a modal editing surface — the Dialog
          primitive gives it role=dialog + aria-modal + aria-labelledby, a focus
          trap, Escape-to-close, and focus restore to the Add/Edit trigger.
          A11Y-10: the field set is grouped in a <fieldset>/<legend>. */}
      <Dialog open={editing} title={providers.some((p) => p.name === form.name) ? "Edit provider" : "New provider"} onClose={() => setEditing(false)}>
        <div className="provider-editor">
        <div className="editor-heading"><span className="visually-hidden">Provider details</span><button type="button" aria-label="Close provider editor" title="Close" onClick={() => setEditing(false)}>×</button></div>
        <fieldset className="form-grid">
          <legend className="visually-hidden">Provider connection details</legend>
          <label>Name<input value={String(form.name || "")} onChange={(e) => update("name", e.target.value)} /></label>
          <label>Protocol<select value={String(form.protocol)} onChange={(e) => update("protocol", e.target.value)}><option value="openai">OpenAI compatible</option><option value="anthropic">Anthropic compatible</option><option value="claude-code">Claude Code</option></select></label>
          <label className="wide">Base URL<input value={String(form.base_url || "")} placeholder="https://api.example.com/v1" onChange={(e) => update("base_url", e.target.value)} /></label>
          <label>Default model (optional)<ModelChooser
            profile={String(form.name || "")}
            value={String(form.model || "")}
            onChange={(value) => update("model", value)}
            placeholder="Type or choose a model id"
            ariaLabel="Default model"
          /></label>
          <label>Key environment variable<input value={String(form.api_key_env || "")} placeholder="PROVIDER_API_KEY" onChange={(e) => update("api_key_env", e.target.value)} /></label>
          <label>API key<input type="password" autoComplete="off" value={String(form.api_key || "")} placeholder={form.has_api_key ? "Stored; enter to replace" : "Stored locally in .env"} onChange={(e) => update("api_key", e.target.value)} /></label>
          <label>Authentication<select value={String(form.auth_style || "bearer")} onChange={(e) => update("auth_style", e.target.value)}><option value="bearer">Bearer token</option><option value="x-api-key">x-api-key</option></select></label>
          <label>Default modality<select value={String(form.modality || "text")} onChange={(e) => update("modality", e.target.value)}><option value="text">Text</option><option value="image">Image generation</option></select></label>
          <label>Request timeout (seconds)<input type="number" min={0} step={1} value={Number(form.timeout || 0)} onChange={(e) => update("timeout", Number(e.target.value))} /></label>
          <label className="toggle-field"><input type="checkbox" checked={Boolean(form.reasoning)} onChange={(e) => update("reasoning", e.target.checked)} /><span>Request reasoning output</span></label>
          <label>Inference path<input value={String(form.inference_path || "")} placeholder="Protocol default" onChange={(e) => update("inference_path", e.target.value)} /></label>
          <label>Models path<input value={String(form.models_path || "")} placeholder="Protocol default" onChange={(e) => update("models_path", e.target.value)} /></label>
        </fieldset>
        <div className="editor-actions"><button type="button" onClick={() => setEditing(false)}>Cancel</button><button type="button" className="primary-command" disabled={busy} onClick={() => void save()}>Save provider</button></div>
        </div>
      </Dialog>
    </div>
  </details>;
}
