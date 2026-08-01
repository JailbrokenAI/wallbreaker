import { useEffect, useMemo, useState } from "react";
import { v2Api } from "./api";
import { EmptyState, JsonBlock, LoadingState, Panel, VerdictBadge } from "./components";
import type { HistoryEvent, RunSummary } from "./types";

type ViewMode = "stream" | "timeline" | "raw";

function eventData(event: HistoryEvent): Record<string, unknown> {
  try { return JSON.parse(event.structured_json) as Record<string, unknown>; }
  catch { return { raw: event.structured_json }; }
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : JSON.stringify(value, null, 2);
}

function eventContent(event: HistoryEvent): string {
  const data = eventData(event);
  const fields = ["text", "content", "response", "reasoning", "prompt", "request", "reason", "summary", "message", "result"];
  for (const field of fields) {
    const value = textValue(data[field]);
    if (value) return value;
  }
  return JSON.stringify(data, null, 2);
}

function FacetMenu({ label, values, selected, onChange }: {
  label: string;
  values: string[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  return <details className="v2-facet-menu"><summary>{label}<span>{selected.size}/{values.length}</span></summary><div><header><button type="button" onClick={() => onChange(new Set(values))}>All</button><button type="button" onClick={() => onChange(new Set())}>None</button></header>{values.map((value) => <label key={value}><input type="checkbox" checked={selected.has(value)} onChange={(event) => { const next = new Set(selected); if (event.target.checked) next.add(value); else next.delete(value); onChange(next); }} /><span>{value}</span></label>)}</div></details>;
}

function download(filename: string, contents: string, type = "application/json") {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export function RunsExplorer() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selectedRun, setSelectedRun] = useState("");
  const [runQuery, setRunQuery] = useState("");
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [view, setView] = useState<ViewMode>("stream");
  const [query, setQuery] = useState("");
  const [types, setTypes] = useState<Set<string>>(new Set());
  const [actors, setActors] = useState<Set<string>>(new Set());
  const [verdicts, setVerdicts] = useState<Set<string>>(new Set());
  const [selectedEvent, setSelectedEvent] = useState<HistoryEvent | null>(null);

  const loadRuns = () => v2Api.historyRuns().then((payload) => {
    const rows = payload.items.map((row) => ({
      name: String(row.run_name || ""),
      time: String(row.last_timestamp || row.first_timestamp || ""),
      records: Number(row.event_count || 0),
      hits: Object.values((row.verdicts || {}) as Record<string, number>).reduce((sum, count) => sum + Number(count || 0), 0),
    })).filter((run) => run.name);
    setRuns(rows);
    setSelectedRun((current) => current || rows[0]?.name || "");
  }).catch(() => v2Api.runs().then((rows) => { setRuns(rows); setSelectedRun((current) => current || rows[0]?.name || ""); }).catch(() => setRuns([])));
  useEffect(() => { loadRuns(); }, []);
  useEffect(() => {
    if (!selectedRun) { setEvents([]); return; }
    setLoading(true); setMessage("");
    v2Api.historyEvents({ run_name: selectedRun, limit: 5000, order: "asc" }).then((payload) => {
      setEvents(payload.items);
      setSelectedEvent(payload.items[0] || null);
      setTypes(new Set(payload.items.map((event) => event.event_type || "unknown")));
      setActors(new Set(payload.items.map((event) => event.actor || "system")));
      setVerdicts(new Set(payload.items.map((event) => event.verdict).filter(Boolean)));
      if (payload.total > payload.items.length) setMessage(`Showing the first ${payload.items.length} of ${payload.total} events.`);
    }).catch((reason) => { setMessage(reason instanceof Error ? reason.message : "Unable to load run events"); setEvents([]); }).finally(() => setLoading(false));
  }, [selectedRun]);

  const typeValues = useMemo(() => [...new Set(events.map((event) => event.event_type || "unknown"))].sort(), [events]);
  const actorValues = useMemo(() => [...new Set(events.map((event) => event.actor || "system"))].sort(), [events]);
  const verdictValues = useMemo(() => [...new Set(events.map((event) => event.verdict).filter(Boolean))].sort(), [events]);
  const filtered = useMemo(() => events.filter((event) => {
    if (!types.has(event.event_type || "unknown")) return false;
    if (!actors.has(event.actor || "system")) return false;
    if (event.verdict && !verdicts.has(event.verdict)) return false;
    const needle = query.trim().toLowerCase();
    return !needle || `${event.event_type} ${event.actor} ${event.technique} ${event.verdict} ${eventContent(event)}`.toLowerCase().includes(needle);
  }), [events, types, actors, verdicts, query]);
  const visibleRuns = (runs || []).filter((run) => !runQuery || `${run.name} ${run.time || ""}`.toLowerCase().includes(runQuery.toLowerCase()));
  const streamText = filtered.map((event) => `[${event.timestamp}] ${event.actor || "system"} · ${event.event_type}${event.technique ? ` · ${event.technique}` : ""}${event.verdict ? ` · ${event.verdict}` : ""}\n${eventContent(event)}`).join("\n\n");

  if (!runs) return <LoadingState label="Loading runs and logs" />;
  return <div className="v2-page v2-runs-explorer">
    <Panel title="Runs and logs" meta={`${runs.length} retained`}>
      <div className="v2-filterbar"><input aria-label="Search runs" value={runQuery} onChange={(event) => setRunQuery(event.target.value)} placeholder="Search runs" /><button type="button" className="v2-button v2-button-small" onClick={async () => { setMessage("Rebuilding index…"); try { await v2Api.rebuildHistory(); await loadRuns(); setMessage("History index rebuilt from canonical JSONL."); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Index rebuild failed"); } }}>Rebuild index</button></div>
      <div className="v2-run-list">{visibleRuns.map((run) => <button type="button" key={run.name} className={selectedRun === run.name ? "active" : ""} onClick={() => setSelectedRun(run.name)}><strong>{run.name}</strong><span>{run.records || 0} events / {run.hits || 0} verdicts</span><small>{run.time || "Timestamp unavailable"}</small></button>)}</div>
      {!visibleRuns.length && <EmptyState title="No run logs match" />}
    </Panel>
    <Panel title={selectedRun || "Select a run"} meta={`${filtered.length} of ${events.length} events visible`}>
      <div className="v2-log-toolbar"><div className="v2-segmented" role="tablist" aria-label="Log view"><button type="button" className={view === "stream" ? "active" : ""} onClick={() => setView("stream")}>Stream</button><button type="button" className={view === "timeline" ? "active" : ""} onClick={() => setView("timeline")}>Timeline</button><button type="button" className={view === "raw" ? "active" : ""} onClick={() => setView("raw")}>Raw JSON</button></div><label className="v2-log-search"><span className="v2-sr-only">Search selected run</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search this run" /></label><FacetMenu label="Event types" values={typeValues} selected={types} onChange={setTypes} /><FacetMenu label="Actors" values={actorValues} selected={actors} onChange={setActors} />{verdictValues.length > 0 && <FacetMenu label="Verdicts" values={verdictValues} selected={verdicts} onChange={setVerdicts} />}<button type="button" className="v2-button v2-button-small" disabled={!filtered.length} onClick={() => download(`${selectedRun || "run"}-filtered.json`, JSON.stringify(filtered.map(eventData), null, 2))}>Export visible</button></div>
      {message && <p className="v2-inline-status" role="status">{message}</p>}
      {loading && <LoadingState label="Loading complete event stream" />}
      {!loading && !filtered.length && <EmptyState title="No entries are selected" detail="Enable one or more event types and actors, or clear the text search." />}
      {!loading && filtered.length > 0 && view === "stream" && <div className="v2-full-stream"><header><span>Chronological stream</span><button type="button" className="v2-button v2-button-small" onClick={() => navigator.clipboard.writeText(streamText)}>Copy stream</button></header>{filtered.map((event) => <article key={event.id} className={`v2-stream-${event.actor || "system"}`}><div><time>{event.timestamp}</time><strong>{event.actor || "system"}</strong><span>{event.event_type}</span>{event.technique && <span>{event.technique}</span>}{event.verdict && <VerdictBadge verdict={event.verdict} />}</div><pre>{eventContent(event)}</pre></article>)}</div>}
      {!loading && filtered.length > 0 && view === "timeline" && <div className="v2-history-browser v2-log-timeline"><div className="v2-history-events">{filtered.map((event) => <button type="button" key={event.id} className={selectedEvent?.id === event.id ? "active" : ""} onClick={() => setSelectedEvent(event)}><span><strong>{event.event_type}</strong>{event.verdict && <VerdictBadge verdict={event.verdict} />}</span><span>{event.actor || "system"} / {event.technique || "unclassified"}</span><small>{event.timestamp}</small></button>)}</div><div className="v2-history-inspector">{selectedEvent ? <><dl className="v2-kv"><div><dt>Run</dt><dd>{selectedEvent.run_name}</dd></div><div><dt>Sequence</dt><dd>{selectedEvent.sequence}</dd></div><div><dt>Actor</dt><dd>{selectedEvent.actor || "--"}</dd></div><div><dt>Latency</dt><dd>{selectedEvent.latency_ms ?? "--"} ms</dd></div><div><dt>Tokens</dt><dd>{selectedEvent.input_tokens ?? 0} / {selectedEvent.output_tokens ?? 0}</dd></div><div><dt>Inference</dt><dd>{selectedEvent.inference_id || "--"}</dd></div></dl><JsonBlock value={eventData(selectedEvent)} /></> : <EmptyState title="Select an event" />}</div></div>}
      {!loading && filtered.length > 0 && view === "raw" && <pre className="v2-raw-stream">{filtered.map((event) => JSON.stringify(eventData(event))).join("\n")}</pre>}
    </Panel>
  </div>;
}
