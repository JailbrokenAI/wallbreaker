import { zh } from "../i18n/zh";

export function ShortcutsHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="palette-backdrop" onMouseDown={onClose} role="presentation">
      <div
        className="shortcuts-card"
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={zh.shortcuts.title}
      >
        <div className="shortcuts-head">
          <h3>{zh.shortcuts.title}</h3>
          <button type="button" className="ghost-command" onClick={onClose}>
            {zh.common.close}
          </button>
        </div>
        <div className="shortcuts-grid">
          {zh.shortcuts.rows.map((row) => (
            <div key={row.keys} className="shortcuts-row">
              <kbd>{row.keys}</kbd>
              <span>{row.action}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
