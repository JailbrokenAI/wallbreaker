import { useEffect, useMemo, useState } from "react";
import { v2Api } from "./api";
import { EmptyState, LoadingState, Panel, VerdictBadge } from "./components";
import type { HistoryEvent } from "./types";

interface IndexedRun {
  run_name: string;
  first_timestamp?: string;
  last_timestamp?: string;
  event_count?: number;
  verdicts?: Record<string, number>;
}

interface RunReport {
  run_name: string;
  scorecard: Record<string, unknown>;
  coverage: Record<string, unknown>;
  findings: Array<Record<string, unknown>>;
  export: Record<string, unknown>;
  markdown: string;
}

const STRICT_HITS = new Set(["COMPLIED", "SUCCESS", "BYPASS", "JAILBROKEN"]);

function stats(run: IndexedRun) {
  const verdicts = run.verdicts || {};
  const graded = Object.values(verdicts).reduce((sum, count) => sum + Number(count || 0), 0);
  const hits = Object.entries(verdicts).reduce((sum, [label, count]) => sum + (STRICT_HITS.has(label.toUpperCase()) ? Number(count || 0) : 0), 0);
  return { graded, hits, asr: graded ? hits / graded : 0 };
}

function eventRecord(event: HistoryEvent): Record<string, unknown> {
  try { return JSON.parse(event.structured_json) as Record<string, unknown>; }
  catch { return { raw: event.structured_json }; }
}

function saveFile(filename: string, contents: string, type: string) {
  const url = URL.createObjectURL(new Blob([contents], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function pct(value: number) { return `${Math.round(value * 100)}%`; }

export function ReportsDashboard() {
  const [runs, setRuns] = useState<IndexedRun[] | null>(null);
  const [scope, setScope] = useState("all");
  const [report, setReport] = useState<RunReport | null>(null);
  const [events, setEvents] = useState<HistoryEvent[]>([]);
  const [loadingReport, setLoadingReport] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    v2Api.historyRuns(1000).then((payload) => setRuns(payload.items.map((row) => ({
      run_name: String(row.run_name || ""),
      first_timestamp: String(row.first_timestamp || ""),
      last_timestamp: String(row.last_timestamp || ""),
      event_count: Number(row.event_count || 0),
      verdicts: (row.verdicts || {}) as Record<string, number>,
    })).filter((run) => run.run_name))).catch((reason) => { setError(reason instanceof Error ? reason.message : "Unable to load reports"); setRuns([]); });
  }, []);
  useEffect(() => {
    if (scope === "all") { setReport(null); setEvents([]); return; }
    setLoadingReport(true); setError("");
    Promise.all([
      v2Api.report(scope),
      v2Api.historyEvents({ run_name: scope, limit: 5000, order: "asc" }),
    ]).then(([reportPayload, eventPayload]) => {
      setReport(reportPayload as unknown as RunReport);
      setEvents(eventPayload.items);
    }).catch((reason) => { setError(reason instanceof Error ? reason.message : "Unable to build report"); setReport(null); setEvents([]); }).finally(() => setLoadingReport(false));
  }, [scope]);

  const selectedRuns = scope === "all" ? runs || [] : (runs || []).filter((run) => run.run_name === scope);
  const totalEvents = selectedRuns.reduce((sum, run) => sum + Number(run.event_count || 0), 0);
  const totalGraded = selectedRuns.reduce((sum, run) => sum + stats(run).graded, 0);
  const totalHits = selectedRuns.reduce((sum, run) => sum + stats(run).hits, 0);
  const overallAsr = totalGraded ? totalHits / totalGraded : 0;
  const verdictCounts = selectedRuns.reduce<Record<string, number>>((out, run) => {
    Object.entries(run.verdicts || {}).forEach(([label, count]) => { out[label] = (out[label] || 0) + Number(count || 0); });
    return out;
  }, {});
  const techniques = useMemo(() => {
    const values = new Map<string, { total: number; hits: number }>();
    events.forEach((event) => {
      const record = eventRecord(event);
      const name = String(event.technique || record.technique || record.tool || record.name || "").trim();
      const verdict = String(event.verdict || record.label || record.verdict || "").toUpperCase();
      if (!name || !verdict) return;
      const row = values.get(name) || { total: 0, hits: 0 };
      row.total += 1;
      if (STRICT_HITS.has(verdict)) row.hits += 1;
      values.set(name, row);
    });
    return [...values.entries()].map(([name, value]) => ({ name, ...value, asr: value.total ? value.hits / value.total : 0 })).sort((a, b) => b.asr - a.asr || b.total - a.total);
  }, [events]);
  const trend = [...(runs || [])].reverse().slice(-24).map((run) => ({ ...run, ...stats(run) }));
  const portfolioMarkdown = `# Wallbreaker evidence portfolio\n\n- Runs: ${(runs || []).length}\n- Recorded events: ${totalEvents}\n- Graded target responses: ${totalGraded}\n- Strict bypasses: ${totalHits}\n- Aggregate ASR: ${pct(overallAsr)}\n\n## Verdict distribution\n\n${Object.entries(verdictCounts).map(([label, count]) => `- ${label}: ${count}`).join("\n") || "No verdicts recorded."}`;
  const markdown = report?.markdown || portfolioMarkdown;
  const exportPayload = scope === "all"
    ? { scope: "all", generated_at: new Date().toISOString(), summary: { runs: (runs || []).length, events: totalEvents, graded: totalGraded, hits: totalHits, asr: overallAsr }, runs }
    : { scope, generated_at: new Date().toISOString(), report, events: events.map(eventRecord) };

  if (!runs) return <LoadingState label="Building report inventory" />;
  return <div className="v2-page v2-reports-dashboard">
    <section className="v2-report-scope"><div><strong>Evidence report</strong><span>Analyze outcomes, compare runs, inspect techniques, and export an operator-ready record.</span></div><label className="v2-field"><span>Report scope</span><select value={scope} onChange={(event) => setScope(event.target.value)}><option value="all">All indexed runs</option>{runs.map((run) => <option key={run.run_name} value={run.run_name}>{run.run_name}</option>)}</select></label><div><button type="button" className="v2-button" onClick={() => saveFile(`wallbreaker-${scope}-report.md`, markdown, "text/markdown")}>Download Markdown</button><button type="button" className="v2-button v2-button-primary" onClick={() => saveFile(`wallbreaker-${scope}-evidence.json`, JSON.stringify(exportPayload, null, 2), "application/json")}>Export evidence</button></div></section>
    {error && <p className="v2-error" role="alert">{error}</p>}
    <div className="v2-metric-grid v2-report-metrics"><article><span>{scope === "all" ? "Runs" : "Events"}</span><strong>{scope === "all" ? selectedRuns.length : totalEvents}</strong><small>{scope === "all" ? "indexed engagements" : "canonical log records"}</small></article><article><span>Graded responses</span><strong>{totalGraded}</strong><small>judge verdicts recorded</small></article><article><span>Strict bypasses</span><strong>{totalHits}</strong><small>complied or successful</small></article><article><span>Attack success rate</span><strong>{pct(overallAsr)}</strong><small>{report?.scorecard?.overall_grade ? `grade ${String(report.scorecard.overall_grade)}` : "strict aggregate"}</small></article></div>
    {loadingReport ? <LoadingState label="Generating selected run report" /> : <div className="v2-report-grid">
      <Panel title="ASR by run" meta={`${trend.length} recent engagements`}><div className="v2-asr-chart">{trend.map((run) => <div key={run.run_name} title={`${run.run_name}: ${pct(run.asr)} (${run.hits}/${run.graded})`}><span style={{ height: `${Math.max(2, run.asr * 100)}%` }} className={run.asr >= .5 ? "high" : run.asr > 0 ? "medium" : "zero"} /><small>{run.run_name.replace(/^run-/, "").slice(0, 8)}</small></div>)}</div></Panel>
      <Panel title="Verdict distribution" meta={`${totalGraded} graded`}><div className="v2-verdict-bars">{Object.entries(verdictCounts).sort((a, b) => b[1] - a[1]).map(([label, count]) => <article key={label}><header><VerdictBadge verdict={label} /><strong>{count}</strong></header><div><span style={{ width: `${totalGraded ? count / totalGraded * 100 : 0}%` }} /></div><small>{totalGraded ? Math.round(count / totalGraded * 100) : 0}% of graded responses</small></article>)}{!Object.keys(verdictCounts).length && <EmptyState title="No verdicts recorded" />}</div></Panel>
      <Panel title="Technique performance" meta={scope === "all" ? "Select one run for exact attribution" : `${techniques.length} observed`}><div className="v2-technique-table">{scope === "all" && <EmptyState title="Choose an individual run" detail="Technique attribution is calculated from that run’s exact event stream." />}{scope !== "all" && techniques.map((item) => <article key={item.name}><strong>{item.name}</strong><span>{item.hits} / {item.total}</span><div><i style={{ width: `${item.asr * 100}%` }} /></div><b>{pct(item.asr)}</b></article>)}{scope !== "all" && !techniques.length && <EmptyState title="No technique verdicts found" detail="The run is still reportable, but its legacy records do not correlate verdicts to techniques." />}</div></Panel>
      <Panel title="Generated report" meta={scope === "all" ? "Portfolio summary" : `${report?.findings?.length || 0} extracted findings`}><pre className="v2-report-preview">{markdown}</pre></Panel>
    </div>}
  </div>;
}
