import { useEffect, useMemo, useState } from "react";
import { v2Api } from "./api";
import { EmptyState, ErrorBanner, LoadingState, Panel } from "./components";
import type { Capability, CapabilityProperty, ExecutionSummary, HistoryEvent } from "./types";

const WORKFLOW_KEY = "wallbreaker.v2.workflows";
const DRAFT_KEY = "wallbreaker.v2.workflow-draft";

interface WorkflowStep {
  id: string;
  capability_id: string;
  label: string;
  args: Record<string, unknown>;
  continue_on_error: boolean;
}

interface SavedWorkflow {
  id: string;
  alias: string;
  description: string;
  steps: WorkflowStep[];
  created_at: string;
  updated_at: string;
}

interface DraftWorkflow {
  id?: string;
  alias: string;
  description: string;
  steps: WorkflowStep[];
}

const emptyDraft = (): DraftWorkflow => ({ alias: "", description: "", steps: [] });
const uid = () => typeof crypto !== "undefined" && "randomUUID" in crypto
  ? crypto.randomUUID()
  : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

function readJson<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key);
    return value ? JSON.parse(value) as T : fallback;
  } catch {
    return fallback;
  }
}

function defaultsFor(capability: Capability): Record<string, unknown> {
  const values = { ...(capability.defaults || {}) };
  Object.entries(capability.input_schema?.properties || {}).forEach(([name, property]) => {
    if (!(name in values) && property.default !== undefined) values[name] = property.default;
  });
  return values;
}

function fieldValue(value: unknown): string | number {
  return typeof value === "number" ? value : typeof value === "string" ? value : "";
}

function StepField({ name, property, value, onChange }: {
  name: string;
  property: CapabilityProperty;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = property.title || name.replace(/_/g, " ");
  if (property.type === "boolean") return <label className="v2-checkbox-field"><input type="checkbox" checked={Boolean(value)} onChange={(event) => onChange(event.target.checked)} /><span>{label}</span></label>;
  if (property.enum) return <label className="v2-field"><span>{label}</span><select value={String(value ?? "")} onChange={(event) => onChange(event.target.value)}><option value="">Select</option>{property.enum.map((item) => <option key={String(item)}>{String(item)}</option>)}</select>{property.description && <small>{property.description}</small>}</label>;
  if (property.type === "array" || property.type === "object") return <label className="v2-field v2-field-wide"><span>{label}</span><textarea value={value == null ? "" : JSON.stringify(value, null, 2)} onChange={(event) => {
    try { onChange(JSON.parse(event.target.value)); } catch { onChange(event.target.value); }
  }} />{property.description && <small>{property.description}</small>}</label>;
  const numeric = property.type === "number" || property.type === "integer";
  return <label className="v2-field"><span>{label}</span><input type={numeric ? "number" : "text"} value={fieldValue(value)} onChange={(event) => onChange(numeric ? Number(event.target.value) : event.target.value)} />{property.description && <small>{property.description}</small>}</label>;
}

function capabilityFromEvent(event: HistoryEvent, capabilities: Capability[]): Capability | null {
  let structured: Record<string, unknown> = {};
  try { structured = JSON.parse(event.structured_json) as Record<string, unknown>; } catch { /* malformed legacy row */ }
  const nested = [structured, structured.data, structured.request, structured.composed]
    .filter((value): value is Record<string, unknown> => Boolean(value && typeof value === "object" && !Array.isArray(value)));
  const candidates = [
    ...nested.flatMap((record) => [record.capability_id, record.tool, record.name, record.source_tool, record.command]),
    event.tool_id,
    event.technique,
  ].filter(Boolean).map(String);
  for (const candidate of candidates) {
    const normalized = candidate.replace(/^\//, "");
    const match = capabilities.find((capability) =>
      capability.id === normalized
      || capability.id === `tool.${normalized}`
      || capability.id === `tui.${normalized}`
      || capability.title.toLowerCase() === normalized.replace(/[_-]/g, " ").toLowerCase()
    );
    if (match) return match;
  }
  return null;
}

function structuredEvent(event: HistoryEvent): Record<string, unknown> {
  try { return JSON.parse(event.structured_json) as Record<string, unknown>; }
  catch { return {}; }
}

function argsFromEvent(event: HistoryEvent, capability: Capability): Record<string, unknown> {
  const structured = structuredEvent(event);
  const records = [structured, structured.data, structured.request, structured.composed]
    .filter((value): value is Record<string, unknown> => Boolean(value && typeof value === "object" && !Array.isArray(value)));
  const source = records.flatMap((record) => [record.tool_args, record.args, record.input, record.arguments, record.request_body])
    .find((value): value is Record<string, unknown> => Boolean(value && typeof value === "object" && !Array.isArray(value))) || {};
  const properties = capability.input_schema?.properties || {};
  if (!Object.keys(properties).length) return { ...defaultsFor(capability), ...source };
  const inferred: Record<string, unknown> = {};
  Object.keys(properties).forEach((name) => {
    if (name in source) inferred[name] = source[name];
    else {
      const record = records.find((item) => name in item);
      if (record) inferred[name] = record[name];
    }
  });
  if ("arguments" in properties && inferred.arguments == null) {
    inferred.arguments = String(structured.raw_arg || structured.arguments || "");
  }
  return { ...defaultsFor(capability), ...inferred };
}

function eventPreview(event: HistoryEvent): string {
  const row = structuredEvent(event);
  const value = row.text || row.message || row.summary || row.response || row.content || row.prompt || row.request;
  if (typeof value === "string") return value.slice(0, 420);
  return event.structured_json.slice(0, 420);
}

export function WorkflowStudio({ capabilities, initialCapability, onConsumed }: {
  capabilities: Capability[];
  initialCapability?: string;
  onConsumed: () => void;
}) {
  const executable = useMemo(() => capabilities.filter((item) =>
    !item.legacy_only && item.id !== "agent.run" && (item.id.startsWith("tool.") || item.id.startsWith("tui."))
  ), [capabilities]);
  const [saved, setSaved] = useState<SavedWorkflow[]>(() => readJson(WORKFLOW_KEY, []));
  const [draft, setDraft] = useState<DraftWorkflow>(() => readJson(DRAFT_KEY, emptyDraft()));
  const [selectedStep, setSelectedStep] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [tab, setTab] = useState<"build" | "history">("build");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ExecutionSummary | null>(null);
  const [error, setError] = useState("");
  const [runs, setRuns] = useState<Array<Record<string, unknown>> | null>(null);
  const [historyRun, setHistoryRun] = useState("");
  const [historyEvents, setHistoryEvents] = useState<HistoryEvent[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [selectedHistory, setSelectedHistory] = useState<number[]>([]);
  const [historyMappings, setHistoryMappings] = useState<Record<number, string>>({});
  const [expandedHistory, setExpandedHistory] = useState<number[]>([]);
  const [hoveredHistory, setHoveredHistory] = useState<number | null>(null);

  useEffect(() => { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); }, [draft]);
  useEffect(() => { localStorage.setItem(WORKFLOW_KEY, JSON.stringify(saved)); }, [saved]);
  useEffect(() => {
    if (!initialCapability) return;
    const capability = executable.find((item) => item.id === initialCapability);
    if (capability) {
      const step: WorkflowStep = { id: uid(), capability_id: capability.id, label: capability.title, args: defaultsFor(capability), continue_on_error: false };
      setDraft((current) => ({ ...current, steps: [...current.steps, step] }));
      setSelectedStep(step.id);
    }
    onConsumed();
  }, [initialCapability, executable, onConsumed]);
  useEffect(() => {
    if (tab !== "history" || runs) return;
    v2Api.historyRuns().then((payload) => setRuns(payload.items)).catch(() => setRuns([]));
  }, [tab, runs]);
  useEffect(() => {
    if (!historyRun) { setHistoryEvents([]); return; }
    setHistoryLoading(true);
    v2Api.historyEvents({ run_name: historyRun, limit: 2000, order: "asc" })
      .then((payload) => setHistoryEvents(payload.items))
      .catch(() => setHistoryEvents([]))
      .finally(() => setHistoryLoading(false));
  }, [historyRun]);
  useEffect(() => {
    setHistoryMappings({});
    setExpandedHistory([]);
    setHoveredHistory(null);
    setSelectedHistory(historyEvents.filter((event) => capabilityFromEvent(event, executable)).map((event) => event.id));
  }, [historyEvents, executable]);

  const categories = ["All", ...new Set(executable.map((item) => item.category))];
  const filtered = executable.filter((item) =>
    (category === "All" || item.category === category)
    && (!query || `${item.title} ${item.description || ""} ${item.id}`.toLowerCase().includes(query.toLowerCase()))
  );
  const activeStep = draft.steps.find((step) => step.id === selectedStep) || null;
  const activeCapability = activeStep ? executable.find((item) => item.id === activeStep.capability_id) || null : null;
  const applicableHistory = historyEvents.map((event) => {
    const inferred = capabilityFromEvent(event, executable);
    const mapping = historyMappings[event.id];
    const mapped = mapping && mapping !== "__context__" ? executable.find((item) => item.id === mapping) || null : null;
    return { event, inferred, capability: mapping === "__context__" ? null : mapped || inferred };
  });
  const applicableCount = applicableHistory.filter((item) => item.capability).length;
  const selectedApplicableCount = applicableHistory.filter((item) => item.capability && selectedHistory.includes(item.event.id)).length;
  const hoveredEvent = hoveredHistory == null ? null : historyEvents.find((event) => event.id === hoveredHistory) || null;

  const addStep = (capability: Capability) => {
    const step: WorkflowStep = { id: uid(), capability_id: capability.id, label: capability.title, args: defaultsFor(capability), continue_on_error: false };
    setDraft((current) => ({ ...current, steps: [...current.steps, step] }));
    setSelectedStep(step.id);
  };
  const updateStep = (patch: Partial<WorkflowStep>) => setDraft((current) => ({ ...current, steps: current.steps.map((step) => step.id === selectedStep ? { ...step, ...patch } : step) }));
  const moveStep = (id: string, direction: -1 | 1) => setDraft((current) => {
    const index = current.steps.findIndex((step) => step.id === id);
    const destination = index + direction;
    if (index < 0 || destination < 0 || destination >= current.steps.length) return current;
    const steps = [...current.steps];
    [steps[index], steps[destination]] = [steps[destination], steps[index]];
    return { ...current, steps };
  });
  const save = () => {
    const alias = draft.alias.trim();
    if (!alias) { setError("Give the workflow an alias before saving it."); return; }
    if (!draft.steps.length) { setError("Add at least one step before saving the workflow."); return; }
    const now = new Date().toISOString();
    const existing = saved.find((item) => item.id === draft.id || item.alias.toLowerCase() === alias.toLowerCase());
    const record: SavedWorkflow = { id: existing?.id || uid(), alias, description: draft.description.trim(), steps: draft.steps, created_at: existing?.created_at || now, updated_at: now };
    setSaved((current) => [...current.filter((item) => item.id !== record.id && item.alias.toLowerCase() !== alias.toLowerCase()), record].sort((a, b) => a.alias.localeCompare(b.alias)));
    setDraft({ id: record.id, alias: record.alias, description: record.description, steps: record.steps });
    setError("");
  };
  const run = async () => {
    if (!draft.steps.length) { setError("Add at least one step before running the workflow."); return; }
    setRunning(true); setError(""); setResult(null);
    try {
      setResult(await v2Api.createExecution("workflow.run", { alias: draft.alias.trim() || "Unsaved workflow", steps: draft.steps }, "background"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to start workflow"); }
    finally { setRunning(false); }
  };
  const cloneHistory = () => {
    const steps: WorkflowStep[] = [];
    applicableHistory.forEach(({ event, capability }) => {
      if (!capability || !selectedHistory.includes(event.id)) return;
      steps.push({ id: uid(), capability_id: capability.id, label: capability.title, args: argsFromEvent(event, capability), continue_on_error: false });
    });
    setDraft({ alias: historyRun ? `${historyRun}-workflow` : "Cloned workflow", description: `Reconstructed from ${historyRun}`, steps });
    setSelectedStep(steps[0]?.id || "");
    setTab("build");
  };

  return <div className="v2-page v2-workflow-studio">
    <div className="v2-studio-toolbar">
      <div className="v2-segmented" role="tablist"><button type="button" className={tab === "build" ? "active" : ""} onClick={() => setTab("build")}>Build workflow</button><button type="button" className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>Analyze past run</button></div>
      <span>{draft.steps.length} step{draft.steps.length === 1 ? "" : "s"}{draft.id ? " / saved alias" : " / autosaved draft"}</span>
      <div><button type="button" className="v2-button v2-button-small" onClick={() => { setDraft(emptyDraft()); setSelectedStep(""); setResult(null); }}>New</button><button type="button" className="v2-button v2-button-small" onClick={save}>Save alias</button><button type="button" className="v2-button v2-button-primary v2-button-small" disabled={running || !draft.steps.length} onClick={run}>{running ? "Queuing" : "Run workflow"}</button></div>
    </div>
    {error && <ErrorBanner message={error} onDismiss={() => setError("")} />}
    {tab === "build" ? <div className="v2-studio-grid">
      <Panel title="Workflow library" meta={`${saved.length} saved aliases`}>
        <div className="v2-workflow-identity"><label className="v2-field"><span>Alias</span><input value={draft.alias} onChange={(event) => setDraft((current) => ({ ...current, alias: event.target.value }))} placeholder="e.g. pair-then-validate" /></label><label className="v2-field"><span>Purpose</span><textarea value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} placeholder="What this sequence is for" /></label></div>
        <div className="v2-saved-workflows">{saved.map((workflow) => <article key={workflow.id} className={draft.id === workflow.id ? "active" : ""}><button type="button" onClick={() => { setDraft({ id: workflow.id, alias: workflow.alias, description: workflow.description, steps: workflow.steps }); setSelectedStep(workflow.steps[0]?.id || ""); }}><strong>{workflow.alias}</strong><span>{workflow.steps.length} steps</span><small>{workflow.description || "No description"}</small></button><button type="button" title="Clone workflow" onClick={() => { const steps = workflow.steps.map((step) => ({ ...step, id: uid() })); setDraft({ alias: `${workflow.alias}-copy`, description: workflow.description, steps }); setSelectedStep(steps[0]?.id || ""); }}>Clone</button><button type="button" title="Delete workflow" onClick={() => { if (window.confirm(`Delete workflow alias “${workflow.alias}”?`)) setSaved((current) => current.filter((item) => item.id !== workflow.id)); }}>Delete</button></article>)}</div>
      </Panel>
      <Panel title="Sequence" meta="Runs top to bottom">
        {!draft.steps.length && <EmptyState title="Build a sequence" detail="Add a capability from the palette. Each step can be configured before the workflow is saved or run." />}
        <ol className="v2-sequence">{draft.steps.map((step, index) => {
          const capability = executable.find((item) => item.id === step.capability_id);
          return <li key={step.id} className={selectedStep === step.id ? "active" : ""}><span className="v2-sequence-index">{String(index + 1).padStart(2, "0")}</span><button type="button" className="v2-sequence-node" onClick={() => setSelectedStep(step.id)}><strong>{step.label || capability?.title || step.capability_id}</strong><span>{capability?.description || step.capability_id}</span><small>{step.capability_id}{step.continue_on_error ? " / continue on error" : " / stop on error"}</small></button><div className="v2-sequence-actions"><button type="button" disabled={index === 0} onClick={() => moveStep(step.id, -1)} aria-label={`Move step ${index + 1} up`}>↑</button><button type="button" disabled={index === draft.steps.length - 1} onClick={() => moveStep(step.id, 1)} aria-label={`Move step ${index + 1} down`}>↓</button><button type="button" onClick={() => { setDraft((current) => ({ ...current, steps: current.steps.filter((item) => item.id !== step.id) })); if (selectedStep === step.id) setSelectedStep(""); }} aria-label={`Remove step ${index + 1}`}>×</button></div></li>;
        })}</ol>
        {result && <div className="v2-workflow-result"><strong>Workflow queued</strong><span>{result.id}</span><small>Track progress and step events in Live or Runs and Logs.</small></div>}
      </Panel>
      <Panel title={activeCapability ? "Configure step" : "Capability palette"} meta={activeCapability?.id || `${filtered.length} executable components`}>
        {activeStep && activeCapability ? <div className="v2-step-editor"><div className="v2-step-editor-head"><button type="button" className="v2-text-button" onClick={() => setSelectedStep("")}>← Add another step</button><strong>{activeCapability.title}</strong><span>{activeCapability.description}</span></div><div className="v2-form-grid"><label className="v2-field v2-field-wide"><span>Step label</span><input value={activeStep.label} onChange={(event) => updateStep({ label: event.target.value })} /></label>{Object.entries(activeCapability.input_schema?.properties || {}).map(([name, property]) => <StepField key={name} name={name} property={property} value={activeStep.args[name]} onChange={(value) => updateStep({ args: { ...activeStep.args, [name]: value } })} />)}{!Object.keys(activeCapability.input_schema?.properties || {}).length && <label className="v2-field v2-field-wide"><span>Arguments JSON</span><textarea value={JSON.stringify(activeStep.args, null, 2)} onChange={(event) => { try { updateStep({ args: JSON.parse(event.target.value) }); } catch { /* retain valid value */ } }} /></label>}<label className="v2-checkbox-field v2-field-wide"><input type="checkbox" checked={activeStep.continue_on_error} onChange={(event) => updateStep({ continue_on_error: event.target.checked })} /><span>Continue to the next step if this step fails</span></label></div></div> : <><div className="v2-filterbar"><input aria-label="Search workflow capabilities" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search steps" /><select value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item}>{item}</option>)}</select></div><div className="v2-step-palette">{filtered.map((capability) => <button type="button" key={capability.id} onClick={() => addStep(capability)}><span>＋</span><strong>{capability.title}</strong><small>{capability.category}</small><p>{capability.description || capability.id}</p></button>)}{!filtered.length && <EmptyState title="No executable steps match" />}</div></>}
      </Panel>
    </div> : <div className="v2-history-workflow">
      <Panel title="Past agent runs" meta={`${runs?.length || 0} indexed`}>
        {!runs && <LoadingState label="Loading run history" />}
        <div className="v2-run-list">{(runs || []).map((run) => { const name = String(run.run_name || ""); return <button type="button" key={name} className={historyRun === name ? "active" : ""} onClick={() => setHistoryRun(name)}><strong>{name}</strong><span>{Number(run.event_count || 0)} events</span><small>{String(run.last_timestamp || run.first_timestamp || "")}</small></button>; })}</div>
      </Panel>
      <Panel title={historyRun || "Workflow reconstruction"} meta={historyRun ? `${applicableCount} applicable · ${selectedApplicableCount} selected` : "Choose a run"}>
        {!historyRun && <EmptyState title="Select a historical run" detail="Its chronological event sequence will be reconstructed here." />}
        {historyLoading && <LoadingState label="Reconstructing sequence" />}
        {!historyLoading && historyRun && <><div className="v2-history-sequence-actions"><div><p>Applicable events are preselected. Hover previews any record; click expands it. Unmatched events can be mapped to an executable capability and cloned too.</p>{hoveredEvent && <aside className="v2-history-hover-preview"><strong>{hoveredEvent.event_type}</strong><span>{hoveredEvent.actor || "system"} · {hoveredEvent.timestamp}</span><p>{eventPreview(hoveredEvent)}</p></aside>}</div><div><button type="button" className="v2-text-button" onClick={() => setSelectedHistory(applicableHistory.filter((item) => item.capability).map((item) => item.event.id))}>Select applicable</button><button type="button" className="v2-text-button" onClick={() => setSelectedHistory([])}>Select none</button><button type="button" className="v2-button v2-button-primary" disabled={!selectedApplicableCount} onClick={cloneHistory}>Clone {selectedApplicableCount} selected step{selectedApplicableCount === 1 ? "" : "s"}</button></div></div><ol className="v2-history-sequence">{applicableHistory.map(({ event, inferred, capability }, index) => {
          const expanded = expandedHistory.includes(event.id);
          const checked = Boolean(capability && selectedHistory.includes(event.id));
          return <li key={event.id} className={`${expanded ? "expanded" : ""} ${checked ? "selected" : ""}`} onMouseEnter={() => setHoveredHistory(event.id)} onMouseLeave={() => setHoveredHistory(null)}>
            <input type="checkbox" aria-label={`Include event ${index + 1} in cloned workflow`} disabled={!capability} checked={checked} onChange={(change) => setSelectedHistory((current) => change.target.checked ? [...new Set([...current, event.id])] : current.filter((id) => id !== event.id))} />
            <span>{String(index + 1).padStart(2, "0")}</span><i className={capability ? "recognized" : "context"}>{capability ? "STEP" : "EVENT"}</i>
            <button type="button" className="v2-history-event-summary" aria-expanded={expanded} onClick={() => setExpandedHistory((current) => current.includes(event.id) ? current.filter((id) => id !== event.id) : [...current, event.id])}><strong>{capability?.title || event.event_type}</strong><small>{event.actor || "system"} / {event.technique || "unclassified"} / {event.timestamp}</small><span aria-hidden="true">{expanded ? "−" : "+"}</span></button>
            {expanded && <div className="v2-history-event-detail"><label className="v2-field"><span>Executable step mapping</span><select value={historyMappings[event.id] || capability?.id || "__context__"} onChange={(change) => {
              const capabilityId = change.target.value;
              setHistoryMappings((current) => ({ ...current, [event.id]: capabilityId }));
              setSelectedHistory((current) => capabilityId !== "__context__" ? [...new Set([...current, event.id])] : current.filter((id) => id !== event.id));
            }}><option value="__context__">Context only — do not execute</option>{executable.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.id}</option>)}</select><small>{inferred ? "Automatically matched; choose another capability to override it." : "Map this event when it represents an applicable executable action."}</small></label><pre>{JSON.stringify(structuredEvent(event), null, 2)}</pre></div>}
          </li>;
        })}</ol></>}
      </Panel>
    </div>}
  </div>;
}
