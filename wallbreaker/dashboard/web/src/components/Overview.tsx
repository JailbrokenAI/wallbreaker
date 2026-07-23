import type { Overview as OverviewT } from "../api";
import { AsyncView, type AsyncStatus } from "../primitives/AsyncView";

function Bars({ data }: { data: Record<string, { hits: number; total: number }> }) {
  const rows = Object.entries(data)
    .map(([name, v]) => ({ name, ...v, rate: v.total ? v.hits / v.total : 0 }))
    .sort((a, b) => b.rate - a.rate)
    .slice(0, 12);
  if (!rows.length) return <div className="empty">No technique data in the latest run.</div>;
  return (
    <>
      {rows.map((r) => (
        <div className="bar-row" key={r.name}>
          <div className="name" title={r.name}>{r.name}</div>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${r.rate * 100}%` }} /></div>
          <div className="val">{r.hits}/{r.total}</div>
        </div>
      ))}
    </>
  );
}

export function Overview({
  ov,
  status = ov ? "data" : "loading",
  error = null,
  onRetry,
}: {
  ov: OverviewT | null;
  status?: AsyncStatus;
  error?: string | null;
  onRetry?: () => void;
}) {
  // REL-9: a failed overview load shows an error card + Retry via AsyncView,
  // never a permanent "Loading…" spinner (the old `if (!ov)` bug).
  return (
    <AsyncView<OverviewT>
      status={status === "data" && !ov ? "loading" : status}
      data={ov ?? undefined}
      error={error}
      onRetry={onRetry}
    >
      {(data) => <OverviewBody ov={data} />}
    </AsyncView>
  );
}

function OverviewBody({ ov }: { ov: OverviewT }) {
  const sc = ov.scorecard || {};
  const asr = typeof sc.asr === "number" ? `${Math.round(sc.asr * 100)}%` : "—";
  const byTech = (sc.by_technique || {}) as Record<string, { hits: number; total: number }>;

  return (
    <div className="grid">
      <div className="grid cols-4">
        <div className="card stat"><div className="num brand">{asr}</div><div className="lbl">Attack success rate</div></div>
        <div className="card stat"><div className="num bad">{ov.findings_count}</div><div className="lbl">Findings (bypasses)</div></div>
        <div className="card stat"><div className="num accent">{ov.runs_count}</div><div className="lbl">Run logs</div></div>
        <div className="card stat"><div className="num good">{sc.grade ?? "—"}</div><div className="lbl">Robustness grade</div></div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>ASR by technique · {ov.latest_run ?? "no run yet"}</h3>
          <Bars data={byTech} />
        </div>
        <div className="card">
          <h3>Engagement</h3>
          <table>
            <tbody>
              <tr><td className="muted">target</td><td className="mono">{ov.config.target ?? "none"}</td></tr>
              <tr><td className="muted">modality</td><td className="mono">{ov.config.target_modality ?? "text"}</td></tr>
              <tr><td className="muted">profile</td><td className="mono">{ov.config.profile ?? "—"}</td></tr>
              <tr><td className="muted">judge</td><td className="mono">{ov.config.judge ?? "—"}</td></tr>
              <tr><td className="muted">total fires</td><td className="mono">{sc.total ?? 0}</td></tr>
              <tr><td className="muted">hits</td><td className="mono">{sc.hits ?? 0}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
