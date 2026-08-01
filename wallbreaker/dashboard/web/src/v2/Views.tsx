import { useEffect, useState } from "react";
import { arsenalItems, v2Api } from "./api";
import { Profiles } from "../components/Profiles";
import { ProviderManager } from "../components/ProviderManager";
import { TargetOptions } from "../components/TargetOptions";
import { EmptyState, ErrorBanner, JsonBlock, LoadingState, Panel, StatusBadge, VerdictBadge } from "./components";
import type {
  ArsenalItem,
  Capability,
  CapabilityProperty,
  ComposeResult,
  FindingRecord,
  HistoryEvent,
  ExecutionMode,
  ProviderRecord,
  RunSummary,
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

function defaultArguments(capability: Capability): Record<string, unknown> {
  const defaults = { ...(capability.defaults || {}) };
  Object.entries(capability.input_schema?.properties || {}).forEach(([name, property]) => {
    if (!(name in defaults) && property.default !== undefined) defaults[name] = property.default;
  });
  return defaults;
}

function inputValue(value: unknown): string | number {
  return typeof value === "number" ? value : typeof value === "string" ? value : "";
}

function CapabilityField({ name, property, value, required, onChange }: {
  name: string;
  property: CapabilityProperty;
  value: unknown;
  required: boolean;
  onChange: (value: unknown) => void;
}) {
  const label = property.title || name.replace(/_/g, " ");
  if (property.type === "boolean") return <label className="v2-checkbox-field"><input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} /><span>{label}{required ? " (required)" : ""}</span></label>;
  if (property.enum) return <label className="v2-field"><span>{label}</span><select value={String(value ?? "")} required={required} onChange={(event) => onChange(event.target.value)}><option value="">Select</option>{property.enum.map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}</select>{property.description && <small>{property.description}</small>}</label>;
  if (property.type === "array" || property.type === "object") return <label className="v2-field"><span>{label}</span><textarea value={value == null ? "" : JSON.stringify(value, null, 2)} onChange={(event) => {
    try { onChange(JSON.parse(event.target.value)); } catch { onChange(event.target.value); }
  }} placeholder={property.type === "array" ? "[]" : "{}"} />{property.description && <small>{property.description}</small>}</label>;
  return <label className="v2-field"><span>{label}</span><input type={property.type === "number" || property.type === "integer" ? "number" : "text"} value={inputValue(value)} required={required} onChange={(event) => onChange(property.type === "number" || property.type === "integer" ? Number(event.target.value) : event.target.value)} />{property.description && <small>{property.description}</small>}</label>;
}

export function WorkflowsView({ capabilities, initialCapability, onConsumed }: {
  capabilities: Capability[];
  initialCapability?: string;
  onConsumed: () => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [selectedId, setSelectedId] = useState("");
  const selected = capabilities.find((item) => item.id === selectedId) || null;
  const [args, setArgs] = useState<Record<string, unknown>>({});
  const [mode, setMode] = useState<ExecutionMode>("background");
  const [result, setResult] = useState<unknown>(null);
  const [error, setError] = useState("");
  const [running, setRunning] = useState(false);
  const categories = ["All", ...new Set(capabilities.map((item) => item.category))];
  const filtered = capabilities.filter((item) => (category === "All" || item.category === category) && (!query || `${item.title} ${item.description || ""}`.toLowerCase().includes(query.toLowerCase())));

  useEffect(() => {
    if (!initialCapability) return;
    setSelectedId(initialCapability);
    const capability = capabilities.find((item) => item.id === initialCapability);
    if (capability) setArgs(defaultArguments(capability));
    onConsumed();
  }, [initialCapability, capabilities, onConsumed]);

  const choose = (capability: Capability) => { setSelectedId(capability.id); setArgs(defaultArguments(capability)); setResult(null); setError(""); };
  const run = async () => {
    if (!selected) return;
    setRunning(true); setError(""); setResult(null);
    try {
      if (selected.legacy_only) throw new Error("This capability is visible through the legacy catalog, but generic execution requires the V2 capability service.");
      setResult(await v2Api.createExecution(selected.id, args, mode));
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setRunning(false); }
  };

  return <div className="v2-page v2-workflow-grid">
    <Panel title="Capability catalog" meta={`${filtered.length} available`}>
      <div className="v2-filterbar"><input aria-label="Search capabilities" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search capabilities" /><select aria-label="Capability category" value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((value) => <option key={value}>{value}</option>)}</select></div>
      <div className="v2-capability-list">
        {!filtered.length && <EmptyState title="No capabilities found" />}
        {filtered.map((item) => <button type="button" className={selectedId === item.id ? "active" : ""} key={item.id} onClick={() => choose(item)}><strong>{item.title}</strong><span>{item.description || "No description provided."}</span><small>{item.category} / {item.execution_mode || "immediate"}{item.legacy_only ? " / legacy catalog" : ""}</small></button>)}
      </div>
    </Panel>
    <Panel title={selected?.title || "Generic runner"} meta={selected?.id || "Choose a capability to configure it"}>
      {!selected && <EmptyState title="Select a capability" detail="Every capability registered by V2 can be configured and queued here." />}
      {selected && <>
        {error && <ErrorBanner message={error} onDismiss={() => setError("")} />}
        <div className="v2-form-grid">
          {Object.entries(selected.input_schema?.properties || {}).map(([name, property]) => <CapabilityField key={name} name={name} property={property} value={args[name]} required={selected.input_schema?.required?.includes(name) || false} onChange={(value) => setArgs((current) => ({ ...current, [name]: value }))} />)}
          {!Object.keys(selected.input_schema?.properties || {}).length && <label className="v2-field v2-field-wide"><span>Arguments JSON</span><textarea value={JSON.stringify(args, null, 2)} onChange={(event) => { try { setArgs(JSON.parse(event.target.value)); } catch { /* retain last valid object */ } }} /></label>}
          <label className="v2-field"><span>Execution mode</span><select value={mode} onChange={(event) => setMode(event.target.value as ExecutionMode)}><option value="background">Background</option><option value="interactive">Interactive</option></select></label>
        </div>
        <div className="v2-actions"><button type="button" className="v2-button v2-button-primary" disabled={running} onClick={run}>{running ? "Starting" : "Start execution"}</button></div>
        {result != null && <div className="v2-result-stack"><h3>Execution accepted</h3><JsonBlock value={result} /></div>}
      </>}
    </Panel>
  </div>;
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
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [query, setQuery] = useState("");
  const [actor, setActor] = useState("");
  const [eventType, setEventType] = useState("");
  const [verdict, setVerdict] = useState("");
  const [technique, setTechnique] = useState("");
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [eventTotal, setEventTotal] = useState(0);
  const [selectedEvent, setSelectedEvent] = useState<HistoryEvent | null>(null);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    v2Api.historyRuns().then((payload) => setRuns(payload.items.map((row) => ({
      name: String(row.run_name || ""), time: String(row.last_timestamp || row.first_timestamp || ""),
      records: Number(row.event_count || 0), hits: Object.values((row.verdicts || {}) as Record<string, number>).reduce((sum, count) => sum + Number(count || 0), 0),
    })).filter((run) => run.name))).catch(() => v2Api.runs().then(setRuns).catch(() => setRuns([])));
  }, []);
  const searchEvents = async (offset = 0) => {
    setLoadingEvents(true); setMessage("");
    try {
      const result = await v2Api.historyEvents({ q: query, run_name: selected, actor, event_type: eventType, verdict, technique, limit: 200, offset });
      setEvents(result.items); setEventTotal(result.total); setSelectedEvent(result.items[0] || null);
    } catch (reason) { setMessage(errorMessage(reason)); setEvents([]); setEventTotal(0); }
    finally { setLoadingEvents(false); }
  };
  useEffect(() => { searchEvents(); }, [selected]);
  if (!runs) return <LoadingState label="Loading runs" />;
  const filtered = runs.filter((run) => !query || run.name.toLowerCase().includes(query.toLowerCase()));
  return <div className="v2-page v2-runs-grid">
    <Panel title="Runs and logs" meta={`${runs.length} retained`}><div className="v2-filterbar"><input aria-label="Search runs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search runs or full history" /><button type="button" className="v2-button v2-button-small" onClick={() => searchEvents()}>Search all events</button><button type="button" className="v2-button v2-button-small" onClick={async () => { setMessage("Rebuilding index..."); try { await v2Api.rebuildHistory(); setMessage("History index rebuilt from canonical JSONL."); await searchEvents(); } catch (reason) { setMessage(errorMessage(reason)); } }}>Rebuild index</button></div><div className="v2-run-list">{filtered.map((run) => <button type="button" key={run.name} className={selected === run.name ? "active" : ""} onClick={() => setSelected(run.name)}><strong>{run.name}</strong><span>{run.records ?? 0} records / {run.hits ?? 0} verdicts</span><small>{run.time || "Timestamp unavailable"}</small></button>)}</div>{!filtered.length && <EmptyState title="No run logs found" />}</Panel>
    <Panel title={selected || "Historical event search"} meta={`${eventTotal} matching events`}><div className="v2-history-filters"><input aria-label="Actor filter" value={actor} onChange={(event) => setActor(event.target.value)} placeholder="Actor" /><input aria-label="Event type filter" value={eventType} onChange={(event) => setEventType(event.target.value)} placeholder="Event type" /><input aria-label="Verdict filter" value={verdict} onChange={(event) => setVerdict(event.target.value)} placeholder="Verdict" /><input aria-label="Technique filter" value={technique} onChange={(event) => setTechnique(event.target.value)} placeholder="Technique" /><button type="button" className="v2-button v2-button-primary v2-button-small" disabled={loadingEvents} onClick={() => searchEvents()}>{loadingEvents ? "Searching" : "Apply filters"}</button></div>{message && <p className="v2-inline-status" role="status">{message}</p>}<div className="v2-history-browser"><div className="v2-history-events">{events.map((event) => <button type="button" key={event.id} className={selectedEvent?.id === event.id ? "active" : ""} onClick={() => setSelectedEvent(event)}><span><strong>{event.event_type}</strong>{event.verdict && <VerdictBadge verdict={event.verdict} />}</span><span>{event.actor || "system"} / {event.technique || "unclassified"}</span><small>{event.run_name} / {event.timestamp}</small></button>)}{!events.length && <EmptyState title="No indexed events match" detail="Choose a run, broaden the filters, or rebuild the disposable index." />}</div><div className="v2-history-inspector">{selectedEvent ? <><dl className="v2-kv"><div><dt>Run</dt><dd>{selectedEvent.run_name}</dd></div><div><dt>Sequence</dt><dd>{selectedEvent.sequence}</dd></div><div><dt>Actor</dt><dd>{selectedEvent.actor || "--"}</dd></div><div><dt>Latency</dt><dd>{selectedEvent.latency_ms ?? "--"} ms</dd></div><div><dt>Tokens</dt><dd>{selectedEvent.input_tokens ?? 0} / {selectedEvent.output_tokens ?? 0}</dd></div><div><dt>Inference</dt><dd>{selectedEvent.inference_id || "--"}</dd></div></dl><JsonBlock value={JSON.parse(selectedEvent.structured_json)} /></> : <EmptyState title="Select an indexed event" />}</div></div></Panel>
  </div>;
}

function downloadJson(filename: string, value: unknown) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function ReportsView() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [findings, setFindings] = useState<FindingRecord[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => { Promise.all([v2Api.runs(), v2Api.findings()]).then(([runRows, findingRows]) => { setRuns(runRows); setFindings(findingRows); }).finally(() => setLoading(false)); }, []);
  if (loading) return <LoadingState label="Preparing report data" />;
  const hits = runs.reduce((sum, run) => sum + (run.hits || 0), 0);
  const records = runs.reduce((sum, run) => sum + (run.records || 0), 0);
  return <div className="v2-page"><div className="v2-metric-grid"><article><span>Runs</span><strong>{runs.length}</strong></article><article><span>Records</span><strong>{records}</strong></article><article><span>Hits</span><strong>{hits}</strong></article><article><span>Findings</span><strong>{findings.length}</strong></article></div><Panel title="Evidence export" meta="Portable local JSON"><div className="v2-report-actions"><p>Export the currently available run summaries and finding records without altering canonical JSONL history.</p><button type="button" className="v2-button v2-button-primary" disabled={!runs.length && !findings.length} onClick={() => downloadJson(`wallbreaker-report-${new Date().toISOString().slice(0, 10)}.json`, { exported_at: new Date().toISOString(), runs, findings })}>Download report data</button></div></Panel></div>;
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
