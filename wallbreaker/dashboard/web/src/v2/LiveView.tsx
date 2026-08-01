import { useEffect, useMemo, useRef, useState } from "react";
import { v2Api } from "./api";
import {
  actorLabel,
  EmptyState,
  ErrorBanner,
  formatDuration,
  formatTime,
  formatTokens,
  JsonBlock,
  Panel,
  StatusBadge,
  VerdictBadge,
} from "./components";
import type { EventEnvelope, ExecutionSummary } from "./types";

interface TechniqueChoice { name: string; description?: string; control?: boolean }

type InspectorTab = "summary" | "conversation" | "evidence" | "judge" | "request" | "raw" | "artifacts";

const INSPECTOR_TABS: Array<{ id: InspectorTab; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "conversation", label: "Conversation" },
  { id: "evidence", label: "Evidence" },
  { id: "judge", label: "Judge" },
  { id: "request", label: "Request" },
  { id: "raw", label: "Raw" },
  { id: "artifacts", label: "Artifacts" },
];

function eventStatus(event: EventEnvelope): "pass" | "fail" | "bypass" | "inconclusive" {
  const value = `${event.verdict || ""} ${event.kind}`.toLowerCase();
  if (value.includes("bypass") || value.includes("complied")) return "bypass";
  if (value.includes("partial") || value.includes("inconclusive")) return "inconclusive";
  if (value.includes("error") || value.includes("fail")) return "fail";
  return "pass";
}

function eventTitle(event: EventEnvelope): string {
  return event.summary || event.text || event.kind.replace(/_/g, " ");
}

function valueAt(event: EventEnvelope, key: string): unknown {
  return event.data?.[key] ?? (event.raw && typeof event.raw === "object" ? (event.raw as Record<string, unknown>)[key] : undefined);
}

function Inspector({ event }: { event: EventEnvelope | null }) {
  const [tab, setTab] = useState<InspectorTab>("summary");
  useEffect(() => setTab("summary"), [event?.id]);

  if (!event) return <aside className="v2-inspector"><EmptyState title="Select an event" detail="Matrix cells and timeline rows open synchronized evidence here." /></aside>;
  const content = (() => {
    if (tab === "raw") return <JsonBlock value={event.raw ?? event} />;
    if (tab === "conversation") return <JsonBlock value={valueAt(event, "conversation") || valueAt(event, "messages")} empty="No conversation was attached to this event." />;
    if (tab === "evidence") return <JsonBlock value={valueAt(event, "evidence") || valueAt(event, "key_evidence")} empty="No structured evidence was attached." />;
    if (tab === "judge") return <JsonBlock value={valueAt(event, "judging") || valueAt(event, "judge")} empty="No judge record was attached." />;
    if (tab === "request") return <JsonBlock value={valueAt(event, "request")} empty="No normalized request was attached." />;
    if (tab === "artifacts") return <JsonBlock value={valueAt(event, "artifacts") || valueAt(event, "artifact")} empty="No artifacts were attached." />;
    return (
      <div className="v2-inspector-summary">
        <div className="v2-inspector-heading">
          <div><span>Selected event</span><h3>{eventTitle(event)}</h3></div>
          <VerdictBadge verdict={event.verdict} />
        </div>
        <dl className="v2-kv">
          <div><dt>Actor</dt><dd>{actorLabel(event)}</dd></div>
          <div><dt>Round</dt><dd>{event.round ?? "--"}</dd></div>
          <div><dt>Strategy</dt><dd>{event.strategy || "Unclassified"}</dd></div>
          <div><dt>Time</dt><dd>{formatTime(event.timestamp)}</dd></div>
          <div><dt>Latency</dt><dd>{formatDuration(event.latency_ms)}</dd></div>
          <div><dt>Tokens in / out</dt><dd>{formatTokens(event.input_tokens, event.output_tokens)}</dd></div>
        </dl>
        <div className="v2-inspector-section"><h4>Content</h4><JsonBlock value={event.text || event.summary} empty="No text content recorded." /></div>
        {event.verdict && <div className="v2-inspector-section"><h4>Verdict</h4><VerdictBadge verdict={event.verdict} /></div>}
      </div>
    );
  })();

  return (
    <aside className="v2-inspector" aria-label="Evidence inspector">
      <header><div><h2>Evidence inspector</h2><span className="v2-mono">ID {event.id}</span></div></header>
      <div className="v2-inspector-tabs" role="tablist" aria-label="Evidence detail">
        {INSPECTOR_TABS.map((item) => <button
          type="button"
          key={item.id}
          role="tab"
          aria-selected={tab === item.id}
          className={tab === item.id ? "active" : ""}
          onClick={() => setTab(item.id)}
        >{item.label}</button>)}
      </div>
      <div className="v2-inspector-body">{content}</div>
    </aside>
  );
}

function StrategyMatrix({ events, selected, onSelect, maxRounds }: {
  events: EventEnvelope[];
  selected: EventEnvelope | null;
  onSelect: (event: EventEnvelope) => void;
  maxRounds?: number;
}) {
  const strategies = useMemo(() => {
    const rows = new Map<string, Map<number, EventEnvelope>>();
    events.forEach((event) => {
      if (!event.strategy || !event.round) return;
      if (!rows.has(event.strategy)) rows.set(event.strategy, new Map());
      const existing = rows.get(event.strategy)?.get(event.round);
      if (!existing || event.sequence > existing.sequence) rows.get(event.strategy)?.set(event.round, event);
    });
    return [...rows.entries()];
  }, [events]);
  const observedMax = Math.max(0, ...events.map((event) => event.round || 0));
  const rounds = Math.max(1, Math.min(20, maxRounds || observedMax || 8));

  if (!strategies.length) return <EmptyState title="No strategy rounds recorded" detail="The matrix will populate as strategy and round events arrive." />;
  return (
    <div className="v2-matrix-scroll">
      <table className="v2-matrix">
        <thead><tr><th>Strategy</th>{Array.from({ length: rounds }, (_, index) => <th key={index}>{index + 1}</th>)}<th>Bypass</th></tr></thead>
        <tbody>{strategies.map(([strategy, row], rowIndex) => {
          const bypasses = [...row.values()].filter((event) => eventStatus(event) === "bypass").length;
          return <tr key={strategy}>
            <th><span>{String(rowIndex + 1).padStart(2, "0")}</span>{strategy}</th>
            {Array.from({ length: rounds }, (_, index) => {
              const event = row.get(index + 1);
              const status = event ? eventStatus(event) : "not-run";
              const label = event ? `${status}, round ${index + 1}` : `Not run, round ${index + 1}`;
              return <td key={index}>
                {event ? <button
                  type="button"
                  className={`v2-matrix-cell ${status} ${selected?.id === event.id ? "selected" : ""}`}
                  aria-label={`${strategy}: ${label}`}
                  title={label}
                  onClick={() => onSelect(event)}
                >{status === "inconclusive" ? "I" : status.charAt(0).toUpperCase()}</button> : <span className="v2-matrix-empty">-</span>}
              </td>;
            })}
            <td className="v2-mono">{bypasses}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
  );
}

function Timeline({ events, selected, onSelect, liveTail, setLiveTail, unread, markRead }: {
  events: EventEnvelope[];
  selected: EventEnvelope | null;
  onSelect: (event: EventEnvelope) => void;
  liveTail: boolean;
  setLiveTail: (value: boolean) => void;
  unread: number;
  markRead: () => void;
}) {
  const [search, setSearch] = useState("");
  const [actor, setActor] = useState("all");
  const [kind, setKind] = useState("all");
  const [verdict, setVerdict] = useState("all");
  const bodyRef = useRef<HTMLDivElement>(null);
  const actors = useMemo(() => [...new Set(events.map(actorLabel))].sort(), [events]);
  const kinds = useMemo(() => [...new Set(events.map((event) => event.kind))].sort(), [events]);
  const verdicts = useMemo(() => [...new Set(events.map((event) => event.verdict).filter(Boolean) as string[])].sort(), [events]);
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return events.filter((event) => {
      if (actor !== "all" && actorLabel(event) !== actor) return false;
      if (kind !== "all" && event.kind !== kind) return false;
      if (verdict !== "all" && event.verdict !== verdict) return false;
      return !query || `${eventTitle(event)} ${event.strategy || ""} ${actorLabel(event)} ${event.verdict || ""}`.toLowerCase().includes(query);
    });
  }, [events, search, actor, kind, verdict]);

  useEffect(() => {
    if (liveTail) bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [filtered.length, liveTail]);

  return (
    <Panel
      title="Event timeline"
      meta={`${filtered.length} of ${events.length} events`}
      className="v2-timeline-panel"
      actions={<>
        <label className="v2-switch"><input type="checkbox" checked={liveTail} onChange={(event) => setLiveTail(event.target.checked)} /><span>Live tail</span></label>
        {unread > 0 && <button type="button" className="v2-button v2-button-small" onClick={markRead}>{unread} unread / mark read</button>}
      </>}
    >
      <div className="v2-filterbar">
        <label className="v2-search"><span className="v2-sr-only">Search events</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search events, strategies, actors" /></label>
        <label><span className="v2-sr-only">Actor</span><select value={actor} onChange={(event) => setActor(event.target.value)}><option value="all">Actor: All</option>{actors.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label><span className="v2-sr-only">Event type</span><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="all">Event: All</option>{kinds.map((value) => <option key={value}>{value}</option>)}</select></label>
        <label><span className="v2-sr-only">Verdict</span><select value={verdict} onChange={(event) => setVerdict(event.target.value)}><option value="all">Verdict: All</option>{verdicts.map((value) => <option key={value}>{value}</option>)}</select></label>
      </div>
      <div className="v2-timeline" ref={bodyRef} onScroll={(event) => {
        const node = event.currentTarget;
        if (node.scrollHeight - node.scrollTop - node.clientHeight > 24 && liveTail) setLiveTail(false);
      }}>
        <div className="v2-timeline-head"><span>Time</span><span>Actor</span><span>Event</span><span>Details</span><span>Tokens</span><span>Latency</span></div>
        {!filtered.length && <EmptyState title="No events match these filters" detail={events.length ? "Clear a filter to reveal recorded events." : "Events will appear here when a run starts or a historical run is selected."} />}
        {filtered.map((event) => <button
          type="button"
          key={event.id}
          className={`v2-event-row v2-actor-${actorLabel(event).toLowerCase()} ${selected?.id === event.id ? "selected" : ""}`}
          onClick={() => onSelect(event)}
        >
          <span className="v2-mono">{formatTime(event.timestamp)}</span>
          <span className="v2-event-actor"><i aria-hidden="true">●</i>{actorLabel(event)}</span>
          <span>{event.kind.replace(/_/g, " ")}{event.verdict && <VerdictBadge verdict={event.verdict} />}</span>
          <span title={eventTitle(event)}>{eventTitle(event)}</span>
          <span className="v2-mono">{formatTokens(event.input_tokens, event.output_tokens)}</span>
          <span className="v2-mono">{formatDuration(event.latency_ms)}</span>
        </button>)}
      </div>
    </Panel>
  );
}

function AttackerSwitcher({ execution, onRefresh }: { execution: ExecutionSummary; onRefresh: () => void }) {
  const [providers, setProviders] = useState<Array<{ name: string }>>([]);
  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [working, setWorking] = useState(false);
  useEffect(() => { v2Api.providers().then((items) => setProviders(items.map((item) => ({ name: item.name })))).catch(() => setProviders([])); }, []);
  const submit = async () => {
    if (!provider || !model.trim()) return;
    setWorking(true); setStatus("");
    try {
      await v2Api.switchAttacker(execution, { provider, model: model.trim() });
      setStatus("Attacker switched; the conversation context is preserved.");
      onRefresh();
    } catch (reason) { setStatus(reason instanceof Error ? reason.message : "Unable to switch attacker"); }
    finally { setWorking(false); }
  };
  return <section className="v2-attacker-switch" aria-label="Switch attacker while paused"><strong>Hot-switch attacker</strong><select aria-label="Attacker provider" value={provider} onChange={(event) => setProvider(event.target.value)}><option value="">Provider</option>{providers.map((item) => <option key={item.name}>{item.name}</option>)}</select><input aria-label="Attacker model" value={model} onChange={(event) => setModel(event.target.value)} placeholder="Model ID" /><button type="button" className="v2-button v2-button-small" disabled={working || !provider || !model.trim()} onClick={submit}>{working ? "Switching" : "Switch"}</button>{status && <span role="status">{status}</span>}</section>;
}

function RunStrip({ execution, onRefresh }: { execution: ExecutionSummary | null; onRefresh: () => void }) {
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const act = async (action: "pause" | "resume" | "cancel") => {
    if (!execution) return;
    if (action === "cancel" && !window.confirm("Hard stop this execution? In-flight work will be cancelled.")) return;
    setWorking(true);
    setError("");
    try {
      if (action === "pause") await v2Api.pause(execution);
      if (action === "resume") await v2Api.resume(execution);
      if (action === "cancel") await v2Api.cancel(execution);
      onRefresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Control action failed");
    } finally {
      setWorking(false);
    }
  };
  const progress = execution?.max_rounds ? Math.min(100, ((execution.current_round || 0) / execution.max_rounds) * 100) : 0;
  return <>
    <header className="v2-run-strip">
      <div className="v2-strip-field"><span>Target</span><strong>{execution?.target || "No active target"}</strong></div>
      <div className="v2-strip-field"><span>Attacker</span><strong>{execution?.attacker || "--"}</strong></div>
      <div className="v2-strip-field"><span>Judge</span><strong>{execution?.judge || "--"}</strong></div>
      <div className="v2-strip-progress"><span>Round {execution?.current_round ?? "--"} of {execution?.max_rounds ?? "--"}</span><div><i style={{ width: `${progress}%` }} /></div></div>
      <div className="v2-strip-field"><span>Elapsed</span><strong>{formatDuration(execution?.elapsed_ms)}</strong></div>
      <div className="v2-strip-field"><span>Tokens in / out</span><strong>{formatTokens(execution?.input_tokens, execution?.output_tokens)}</strong></div>
      <div className="v2-strip-state"><span>Connection</span>{execution ? <StatusBadge status={execution.status} /> : <span className="v2-muted">● Offline</span>}</div>
      <div className="v2-strip-actions">
        {execution?.status === "paused" ? <button type="button" className="v2-button" disabled={working} onClick={() => act("resume")}>Resume</button> : <button type="button" className="v2-button" disabled={working || !execution || execution.status !== "running"} onClick={() => act("pause")}>Pause</button>}
        <button type="button" className="v2-button v2-button-danger" disabled={working || !execution || !["running", "paused", "pausing", "queued"].includes(execution.status)} onClick={() => act("cancel")}>Stop run</button>
      </div>
    </header>
    {error && <ErrorBanner message={error} onDismiss={() => setError("")} />}
    {execution?.status === "paused" && execution.source !== "legacy" && <AttackerSwitcher execution={execution} onRefresh={onRefresh} />}
  </>;
}

function RunLauncher({ execution, onRefresh }: { execution: ExecutionSummary | null; onRefresh: () => void }) {
  const [objective, setObjective] = useState("");
  const [maxRounds, setMaxRounds] = useState(20);
  const [maxTokens, setMaxTokens] = useState(8192);
  const [concurrency, setConcurrency] = useState(4);
  const [requestDelay, setRequestDelay] = useState(0);
  const [techniques, setTechniques] = useState<TechniqueChoice[]>([]);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { v2Api.tools().then((items) => setTechniques(items.filter((item) => !item.control).map((item) => ({ name: String(item.name || ""), description: typeof item.description === "string" ? item.description : undefined, control: Boolean(item.control) })).filter((item) => item.name))).catch(() => setTechniques([])); }, []);
  const active = execution && ["queued", "running", "pausing", "paused"].includes(execution.status);
  const start = async () => {
    if (!objective.trim() || active) return;
    setWorking(true); setMessage("");
    try {
      await v2Api.createExecution("agent.run", {
        objective: objective.trim(), max_rounds: maxRounds, max_tokens: maxTokens,
        concurrency, request_delay_ms: requestDelay,
        ...(selected == null ? {} : { enabled_techniques: selected }),
      }, "interactive");
      setMessage("Execution queued. Live events will attach automatically.");
      onRefresh();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Unable to start execution"); }
    finally { setWorking(false); }
  };
  return <details className="v2-launcher" open={!execution || !active}>
    <summary><span><strong>New interactive engagement</strong><small>{active ? "One foreground engagement is already active" : "Configure and start without leaving Live"}</small></span><span>{active ? "Occupied" : "Ready"}</span></summary>
    <div className="v2-launcher-body">
      <label className="v2-field v2-field-wide"><span>Objective</span><textarea value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="Describe the authorized evaluation objective" /></label>
      <div className="v2-form-grid">
        <label className="v2-field"><span>Maximum rounds</span><input type="number" min={1} max={50} value={maxRounds} onChange={(event) => setMaxRounds(Number(event.target.value))} /></label>
        <label className="v2-field"><span>Maximum tokens</span><input type="number" min={1} max={32000} value={maxTokens} onChange={(event) => setMaxTokens(Number(event.target.value))} /></label>
        <label className="v2-field"><span>Concurrency</span><input type="number" min={1} max={32} value={concurrency} onChange={(event) => setConcurrency(Number(event.target.value))} /></label>
        <label className="v2-field"><span>Request delay (ms)</span><input type="number" min={0} max={60000} value={requestDelay} onChange={(event) => setRequestDelay(Number(event.target.value))} /></label>
      </div>
      <details className="v2-techniques"><summary>Technique access <span>{selected == null ? "All available" : `${selected.length} selected`}</span></summary><div><button type="button" className="v2-button v2-button-small" onClick={() => setSelected(null)}>Use all</button><button type="button" className="v2-button v2-button-small" onClick={() => setSelected([])}>Clear</button>{techniques.map((item) => <label key={item.name}><input type="checkbox" checked={selected == null || selected.includes(item.name)} onChange={(event) => setSelected((current) => { const base = current == null ? techniques.map((entry) => entry.name) : current; return event.target.checked ? [...new Set([...base, item.name])] : base.filter((name) => name !== item.name); })} /><span><strong>{item.name}</strong><small>{item.description || "Registered capability"}</small></span></label>)}</div></details>
      <div className="v2-actions"><button type="button" className="v2-button v2-button-primary" disabled={working || !objective.trim() || Boolean(active)} onClick={start}>{working ? "Starting" : "Start engagement"}</button>{message && <span className="v2-inline-status" role="status">{message}</span>}</div>
    </div>
  </details>;
}

function SteeringBar({ execution }: { execution: ExecutionSummary | null }) {
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState("");
  const [sending, setSending] = useState(false);
  const submit = async () => {
    if (!execution || !message.trim()) return;
    setSending(true);
    setStatus("");
    try {
      await v2Api.steer(execution, message.trim());
      setMessage("");
      setStatus("Steering queued for the next safe boundary.");
    } catch (reason) {
      setStatus(reason instanceof Error ? reason.message : "Unable to queue steering");
    } finally { setSending(false); }
  };
  return (
    <section className="v2-steer" aria-label="Steer the attacker">
      <div className="v2-steer-head"><strong>Steer the attacker</strong><span>{execution?.current_round ? `Round ${execution.current_round}` : "No active round"}</span>{status && <span role="status">{status}</span>}</div>
      <div className="v2-steer-row">
        <label><span className="v2-sr-only">Steering message</span><textarea value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => {
          if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); submit(); }
        }} placeholder="Steer or command the attacker. Ctrl Enter sends." /></label>
        <button type="button" className="v2-button v2-button-primary" disabled={!execution || !message.trim() || sending} onClick={submit}>{sending ? "Sending" : "Send"}</button>
      </div>
    </section>
  );
}

export function LiveView({ execution, onRefresh }: { execution: ExecutionSummary | null; onRefresh: () => void }) {
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [selected, setSelected] = useState<EventEnvelope | null>(null);
  const [liveTail, setLiveTail] = useState(true);
  const liveTailRef = useRef(true);
  const [unread, setUnread] = useState(0);
  const [streamState, setStreamState] = useState("idle");

  useEffect(() => { liveTailRef.current = liveTail; if (liveTail) setUnread(0); }, [liveTail]);
  useEffect(() => {
    setEvents([]);
    setSelected(null);
    setUnread(0);
    if (!execution) return;
    if (execution.source === "legacy" && execution.id !== "legacy-active") {
      setStreamState("loading");
      v2Api.legacyEvents(execution.run_id || execution.id).then((loaded) => {
        setEvents(loaded);
        setSelected(loaded.length ? loaded[loaded.length - 1] : null);
        setStreamState("complete");
      }).catch(() => setStreamState("unavailable"));
      return;
    }
    if (execution.source === "legacy") { setStreamState("legacy-live"); return; }
    const controller = new AbortController();
    let reconnect = 0;
    let timer = 0;
    const connect = async () => {
      setStreamState("connected");
      try {
        await v2Api.streamEvents(execution.id, reconnect, (event) => {
          reconnect = Math.max(reconnect, event.sequence);
          setEvents((current) => current.some((item) => item.id === event.id) ? current : [...current, event].sort((a, b) => a.sequence - b.sequence));
          if (!liveTailRef.current) setUnread((current) => current + 1);
        }, controller.signal);
        if (!controller.signal.aborted && ["running", "pausing", "paused"].includes(execution.status)) timer = window.setTimeout(connect, 1400);
      } catch {
        if (!controller.signal.aborted) {
          setStreamState("reconnecting");
          timer = window.setTimeout(connect, 1800);
        }
      }
    };
    connect();
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [execution?.id, execution?.source, execution?.status]);

  useEffect(() => {
    if (liveTail && events.length && !selected) setSelected(events[events.length - 1]);
  }, [events, liveTail, selected]);

  return (
    <div className="v2-live">
      <RunStrip execution={execution} onRefresh={onRefresh} />
      <RunLauncher execution={execution} onRefresh={onRefresh} />
      <div className="v2-live-grid">
        <main className="v2-observatory">
          <Panel title="Strategy by round" meta={`Overview / stream ${streamState}`} className="v2-matrix-panel" actions={<div className="v2-legend"><span className="pass">P Pass</span><span className="fail">F Fail</span><span className="bypass">B Bypass</span><span className="inconclusive">I Inconclusive</span></div>}>
            <StrategyMatrix events={events} selected={selected} onSelect={setSelected} maxRounds={execution?.max_rounds} />
          </Panel>
          <Timeline events={events} selected={selected} onSelect={setSelected} liveTail={liveTail} setLiveTail={setLiveTail} unread={unread} markRead={() => { setUnread(0); setLiveTail(true); }} />
        </main>
        <Inspector event={selected} />
      </div>
      <SteeringBar execution={execution} />
    </div>
  );
}
