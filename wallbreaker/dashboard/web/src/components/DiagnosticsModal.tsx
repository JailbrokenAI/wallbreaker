import type { DiagnosticsReport } from "../desktop";
import { zh } from "../i18n/zh";

export function DiagnosticsModal({
  open,
  report,
  busy,
  onClose,
  onRerun,
  onCopy,
}: {
  open: boolean;
  report: DiagnosticsReport | null;
  busy: boolean;
  onClose: () => void;
  onRerun: () => void;
  onCopy: () => void;
}) {
  if (!open) return null;
  return (
    <div className="palette-backdrop" onMouseDown={onClose} role="presentation">
      <div
        className="diag-card"
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={zh.diagnostics.title}
      >
        <div className="shortcuts-head">
          <h3>
            {zh.diagnostics.title}{" "}
            {report ? (report.ok ? `· ${zh.diagnostics.ok}` : `· ${zh.diagnostics.issues}`) : ""}
          </h3>
          <button type="button" className="ghost-command" onClick={onClose}>
            {zh.common.close}
          </button>
        </div>
        {busy && !report ? <div className="muted">{zh.diagnostics.running}</div> : null}
        {report && (
          <>
            <div className={`diag-summary ${report.ok ? "ok" : "bad"}`}>{report.summary}</div>
            <div className="diag-list">
              {report.checks.map((c) => (
                <div key={c.id} className={`diag-item ${c.ok ? "ok" : "bad"}`}>
                  <div className="diag-flag">{c.ok ? zh.diagnostics.pass : zh.diagnostics.fail}</div>
                  <div>
                    <div className="diag-label">{c.label}</div>
                    <div className="diag-detail mono">{c.detail}</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="desktop-actions">
              <button type="button" className="primary-command" disabled={busy} onClick={onRerun}>
                {busy ? zh.diagnostics.running : zh.diagnostics.rerun}
              </button>
              <button type="button" className="ghost-command" onClick={onCopy}>
                {zh.diagnostics.copy}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
