import type { Overview as OverviewT } from "../api";
import { zh } from "../i18n/zh";

function Bars({ data }: { data: Record<string, { hits: number; total: number }> }) {
  const rows = Object.entries(data)
    .map(([name, v]) => ({ name, ...v, rate: v.total ? v.hits / v.total : 0 }))
    .sort((a, b) => b.rate - a.rate)
    .slice(0, 12);
  if (!rows.length) return <div className="empty">{zh.overview.noTechnique}</div>;
  return (
    <>
      {rows.map((r) => (
        <div className="bar-row" key={r.name}>
          <div className="name" title={r.name}>
            {r.name}
          </div>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${r.rate * 100}%` }} />
          </div>
          <div className="val">
            {r.hits}/{r.total}
          </div>
        </div>
      ))}
    </>
  );
}

export function Overview({ ov }: { ov: OverviewT | null }) {
  if (!ov) return <div className="empty">{zh.common.loading}</div>;
  const sc = ov.scorecard || {};
  const asr = typeof sc.asr === "number" ? `${Math.round(sc.asr * 100)}%` : "—";
  const byTech = (sc.by_technique || {}) as Record<string, { hits: number; total: number }>;

  return (
    <div className="grid">
      <div className="grid cols-4">
        <div className="card stat">
          <div className="num brand">{asr}</div>
          <div className="lbl">{zh.overview.asr}</div>
        </div>
        <div className="card stat">
          <div className="num bad">{ov.findings_count}</div>
          <div className="lbl">{zh.overview.findings}</div>
        </div>
        <div className="card stat">
          <div className="num accent">{ov.runs_count}</div>
          <div className="lbl">{zh.overview.runs}</div>
        </div>
        <div className="card stat">
          <div className="num good">{sc.grade ?? "—"}</div>
          <div className="lbl">{zh.overview.grade}</div>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>
            {zh.overview.byTechnique} · {ov.latest_run ?? zh.overview.noRun}
          </h3>
          <Bars data={byTech} />
        </div>
        <div className="card">
          <h3>{zh.overview.engagement}</h3>
          <table>
            <tbody>
              <tr>
                <td className="muted">{zh.overview.target}</td>
                <td className="mono">{ov.config.target ?? zh.common.none}</td>
              </tr>
              <tr>
                <td className="muted">{zh.overview.modality}</td>
                <td className="mono">{ov.config.target_modality ?? "text"}</td>
              </tr>
              <tr>
                <td className="muted">{zh.overview.profile}</td>
                <td className="mono">{ov.config.profile ?? "—"}</td>
              </tr>
              <tr>
                <td className="muted">{zh.overview.judge}</td>
                <td className="mono">{ov.config.judge ?? "—"}</td>
              </tr>
              <tr>
                <td className="muted">{zh.overview.totalFires}</td>
                <td className="mono">{sc.total ?? 0}</td>
              </tr>
              <tr>
                <td className="muted">{zh.overview.hits}</td>
                <td className="mono">{sc.hits ?? 0}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
