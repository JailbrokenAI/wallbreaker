import { useEffect, useState } from "react";
import { arsenalItems, v2Api } from "./api";
import { Profiles } from "../components/Profiles";
import { ProviderManager } from "../components/ProviderManager";
import { TargetOptions } from "../components/TargetOptions";
import { EmptyState, ErrorBanner, JsonBlock, LoadingState, Panel, StatusBadge, VerdictBadge } from "./components";
import { WorkflowStudio } from "./WorkflowStudio";
import { RunsExplorer } from "./RunsExplorer";
import { ReportsDashboard } from "./ReportsDashboard";
import type {
  ArsenalItem,
  Capability,
  ComposeResult,
  FindingRecord,
  ProviderRecord,
  SettingsRecord,
} from "./types";

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : "Unexpected request failure";
}

function useArsenal() {
  const [items, setItems] = useState<ArsenalItem[] | null>(null);
  useEffect(() => {
    Promise.all([v2Api.presets(), v2Api.transforms(), v2Api.tools()])
      .then(([presets, transforms, tools]) => setItems(arsenalItems(presets, transforms, tools)))
      .catch(() => setItems([]));
  }, []);
  return items;
}

export function ComposeView() {
  const arsenal = useArsenal();
  const presets = (arsenal || []).filter((item) => item.kind === "preset");
  const transforms = (arsenal || []).filter((item) => item.kind === "transform");
  const [request, setRequest] = useState("");
  const [preset, setPreset] = useState("");
  const [selectedTransforms, setSelectedTransforms] = useState<string[]>([]);
  const [system, setSystem] = useState("");
  const [maxTokens, setMaxTokens] = useState(8192);
  const [result, setResult] = useState<ComposeResult | null>(null);
  const [working, setWorking] = useState<"preview" | "fire" | "">("");
  const [error, setError] = useState("");

  const submit = async (action: "preview" | "fire") => {
    if (!request.trim()) return;
    setWorking(action);
    setError("");
    const body = { request, preset: preset || undefined, transforms: selectedTransforms, system: system || undefined, max_tokens: maxTokens };
    try { setResult(action === "preview" ? await v2Api.compose(body) : await v2Api.fire(body)); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setWorking(""); }
  };

  return <div className="v2-page v2-compose-grid">
    <Panel title="Attack composer" meta="Exact payload preview before delivery">
      {error && <ErrorBanner message={error} onDismiss={() => setError("")} />}
      <div className="v2-form-grid">
        <label className="v2-field v2-field-wide"><span>Request</span><textarea value={request} onChange={(event) => setRequest(event.target.value)} placeholder="Enter the authorized evaluation objective or request" /></label>
        <label className="v2-field"><span>Preset</span><select value={preset} onChange={(event) => setPreset(event.target.value)}><option value="">None</option>{presets.map((item) => <option key={item.name}>{item.name}</option>)}</select></label>
        <label className="v2-field"><span>Maximum tokens</span><input type="number" min={1} max={64000} value={maxTokens} onChange={(event) => setMaxTokens(Number(event.target.value))} /></label>
        <label className="v2-field v2-field-wide"><span>System prompt override</span><textarea value={system} onChange={(event) => setSystem(event.target.value)} placeholder="Optional system prompt" /></label>
      </div>
      <fieldset className="v2-check-grid"><legend>Transforms</legend>
        {!transforms.length && <span className="v2-muted">No transforms loaded.</span>}
        {transforms.map((item) => <label key={item.name}><input type="checkbox" checked={selectedTransforms.includes(item.name)} onChange={(event) => setSelectedTransforms((current) => event.target.checked ? [...current, item.name] : current.filter((name) => name !== item.name))} /><span>{item.name}</span></label>)}
      </fieldset>
      <div className="v2-actions">
        <button type="button" className="v2-button" disabled={!request.trim() || !!working} onClick={() => submit("preview")}>{working === "preview" ? "Composing" : "Preview payload"}</button>
        <button type="button" className="v2-button v2-button-primary" disabled={!request.trim() || !!working} onClick={() => submit("fire")}>{working === "fire" ? "Delivering" : "Fire request"}</button>
      </div>
    </Panel>
    <Panel title="Payload and response" meta={result?.run_log || "Nothing sent until you choose Fire request"}>
      {!result && <EmptyState title="No composed payload yet" detail="Preview shows the exact transformed content without contacting the target." />}
      {result && <div className="v2-result-stack">
        <section><h3>Payload</h3><JsonBlock value={result.payload} /></section>
        {result.response != null && <section><h3>Target response</h3>{result.verdict && <VerdictBadge verdict={result.verdict} />}<JsonBlock value={result.response} /></section>}
      </div>}
    </Panel>
  </div>;
}

export function WorkflowsView({ capabilities, initialCapability, onConsumed }: {
  capabilities: Capability[];
  initialCapability?: string;
  onConsumed: () => void;
}) {
  return <WorkflowStudio capabilities={capabilities} initialCapability={initialCapability} onConsumed={onConsumed} />;
}

export function ArsenalView() {
  const items = useArsenal();
  const [kind, setKind] = useState<"all" | ArsenalItem["kind"]>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ArsenalItem | null>(null);
  if (!items) return <LoadingState label="Loading Arsenal" />;
  const filtered = items.filter((item) => (kind === "all" || item.kind === kind) && (!query || `${item.name} ${item.description || ""}`.toLowerCase().includes(query.toLowerCase())));
  return <div className="v2-page v2-library-grid">
    <Panel title="Arsenal" meta={`${filtered.length} items`}>
      <div className="v2-filterbar"><input aria-label="Search Arsenal" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search names and descriptions" /><select aria-label="Arsenal type" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}><option value="all">All types</option><option value="preset">Presets</option><option value="transform">Transforms</option><option value="tool">Tools</option></select></div>
      <div className="v2-library-list">{filtered.map((item) => <button type="button" className={selected?.name === item.name && selected.kind === item.kind ? "active" : ""} key={`${item.kind}-${item.name}`} onClick={() => setSelected(item)}><span className={`v2-kind v2-kind-${item.kind}`}>{item.kind}</span><strong>{item.name}</strong><span>{item.description || "No description provided."}</span></button>)}</div>
    </Panel>
    <Panel title={selected?.name || "Item detail"} meta={selected?.kind}>{selected ? <JsonBlock value={selected.detail} /> : <EmptyState title="Choose an Arsenal item" detail="Inspect exact templates, transform metadata, and tool schemas." />}</Panel>
  </div>;
}

export function FindingsView() {
  const [findings, setFindings] = useState<FindingRecord[] | null>(null);
  const [query, setQuery] = useState("");
  const [verdict, setVerdict] = useState("all");
  const [selected, setSelected] = useState<FindingRecord | null>(null);
  useEffect(() => { v2Api.findings().then(setFindings).catch(() => setFindings([])); }, []);
  if (!findings) return <LoadingState label="Loading findings" />;
  const verdicts = [...new Set(findings.map((item) => item.label).filter(Boolean) as string[])];
  const filtered = findings.filter((item) => (verdict === "all" || item.label === verdict) && (!query || `${item.technique || ""} ${item.reason || ""} ${item.response || ""} ${item.run || ""}`.toLowerCase().includes(query.toLowerCase())));
  return <div className="v2-page v2-library-grid">
    <Panel title="Findings" meta={`${filtered.length} evidence records`}>
      <div className="v2-filterbar"><input aria-label="Search findings" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search evidence, technique, run" /><select aria-label="Finding verdict" value={verdict} onChange={(event) => setVerdict(event.target.value)}><option value="all">All verdicts</option>{verdicts.map((value) => <option key={value}>{value}</option>)}</select></div>
      {!filtered.length && <EmptyState title="No findings match" detail={findings.length ? "Clear filters to see other evidence." : "No findings have been recorded yet."} />}
      <div className="v2-finding-list">{filtered.map((item, index) => <button type="button" className={selected === item ? "active" : ""} key={item.id || `${item.run}-${index}`} onClick={() => setSelected(item)}><div><VerdictBadge verdict={item.label} /><span>{item.technique || "Unclassified"}</span></div><strong>{item.reason || item.response || "Recorded finding"}</strong><small>{item.run || "Unknown run"}{item.ts ? ` / ${item.ts}` : ""}</small></button>)}</div>
    </Panel>
    <Panel title="Finding inspector" meta={selected?.id || selected?.run}>{selected ? <JsonBlock value={selected} /> : <EmptyState title="Select a finding" detail="The complete evidence record, judging, and conversation will appear here." />}</Panel>
  </div>;
}

export function RunsView() {
  return <RunsExplorer />;
}

export function ReportsView() {
  return <ReportsDashboard />;
}

export function ModelsView() {
  const [providers, setProviders] = useState<ProviderRecord[] | null>(null);
  const [testing, setTesting] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => { v2Api.providers().then(setProviders).catch(() => setProviders([])); }, []);
  if (!providers) return <LoadingState label="Loading providers" />;
  const refresh = () => v2Api.providers().then(setProviders).catch(() => setProviders([]));
  return <div className="v2-page"><Panel title="Models and providers" meta={`${providers.length} configured`}>
    {!providers.length && <EmptyState title="No providers configured" detail="Provider management remains available through the current dashboard until V2 configuration endpoints are active." />}
    <div className="v2-provider-grid">{providers.map((provider) => <article key={provider.name}><div><h3>{provider.name}</h3><StatusBadge status={provider.enabled === false ? "paused" : "running"} /></div><dl className="v2-kv"><div><dt>Protocol</dt><dd>{provider.protocol || "--"}</dd></div><div><dt>Model</dt><dd>{provider.model || "--"}</dd></div><div><dt>Modality</dt><dd>{provider.modality || "--"}</dd></div><div><dt>Reasoning</dt><dd>{provider.reasoning ? "Enabled" : "Disabled"}</dd></div><div><dt>Credentials</dt><dd>{provider.has_api_key ? "Configured" : "Not reported"}</dd></div></dl><button type="button" className="v2-button" disabled={!!testing} onClick={async () => { setTesting(provider.name); setMessage(""); try { await v2Api.testProvider(provider.name); setMessage(`${provider.name} responded successfully.`); } catch (reason) { setMessage(errorMessage(reason)); } finally { setTesting(""); } }}>{testing === provider.name ? "Testing" : "Test provider"}</button></article>)}</div>
    {message && <p className="v2-inline-status" role="status">{message}</p>}
  </Panel><Panel title="Provider management" meta="Create, edit, enable, discover, and test"><ProviderManager onChanged={refresh} /></Panel><Panel title="Attacker, target, and judge profiles" meta="Reusable named role assignments"><Profiles onSaved={refresh} /></Panel></div>;
}

export function SettingsView() {
  const [settings, setSettings] = useState<SettingsRecord | null>(null);
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { v2Api.settings().then(setSettings).catch((reason) => setError(errorMessage(reason))); }, []);
  if (!settings && !error) return <LoadingState label="Loading settings" />;
  const agent = settings?.agent || {};
  const setAgent = (key: string, value: number) => setSettings((current) => ({ ...(current || {}), agent: { ...(current?.agent || {}), [key]: value } }));
  const save = async () => {
    if (!settings) return;
    setError(""); setSaved("");
    try { setSettings(await v2Api.saveSettings(settings)); setSaved("Settings saved."); }
    catch (reason) { setError(errorMessage(reason)); }
  };
  return <div className="v2-page v2-settings-page"><Panel title="Operator defaults" meta="Applies to future launches">
    {error && <ErrorBanner message={error} onDismiss={() => setError("")} />}
    <div className="v2-form-grid">
      <label className="v2-field"><span>Maximum rounds</span><input type="number" min={1} max={100} value={agent.max_rounds ?? 20} onChange={(event) => setAgent("max_rounds", Number(event.target.value))} /></label>
      <label className="v2-field"><span>Maximum tokens</span><input type="number" min={1} max={64000} value={agent.max_tokens ?? 8192} onChange={(event) => setAgent("max_tokens", Number(event.target.value))} /></label>
      <label className="v2-field"><span>Concurrency</span><input type="number" min={1} max={64} value={agent.concurrency ?? 4} onChange={(event) => setAgent("concurrency", Number(event.target.value))} /></label>
      <label className="v2-field"><span>Request delay (ms)</span><input type="number" min={0} max={60000} value={agent.request_delay_ms ?? 0} onChange={(event) => setAgent("request_delay_ms", Number(event.target.value))} /></label>
    </div>
    <div className="v2-actions"><button type="button" className="v2-button v2-button-primary" disabled={!settings} onClick={save}>Save defaults</button>{saved && <span className="v2-inline-status" role="status">{saved}</span>}</div>
  </Panel><Panel title="Target delivery controls" meta="Modality, system handling, backend, and judging"><TargetOptions /></Panel><Panel title="Local operator safeguards"><div className="v2-safeguards"><p><strong>History</strong><span>Canonical JSONL remains unchanged; the V2 index is rebuildable.</span></p><p><strong>Credentials</strong><span>Secret values are never displayed by this surface.</span></p><p><strong>Network exposure</strong><span>Keep the dashboard bound to loopback unless remote access is explicitly intended.</span></p></div></Panel></div>;
}
