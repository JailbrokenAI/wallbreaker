import {
  useEffect,
  useState,
  type DragEvent as ReactDragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { api, type RunDetail, type RunModels, type RunSummary } from "../api";
import { emptyPlaceholder, formatTimestamp } from "../format";
import {
  RunDetailView,
  DEFAULT_COLUMNS,
  reorderColumns,
  type ColumnId,
  type ColumnState,
  type RunRecord,
} from "./RunDetailView";

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function hasRecordedModels(models: RunModels | undefined): boolean {
  return !!models?.recorded && !!(models.attacker || models.target || models.judge);
}

function modelSummaryText(models: RunModels | undefined): string {
  if (!hasRecordedModels(models)) return emptyPlaceholder;
  return [
    models?.attacker ? `attacker: ${models.attacker}` : "",
    models?.target ? `target: ${models.target}` : "",
    models?.judge ? `judge: ${models.judge}` : "",
  ].filter(Boolean).join("\n");
}

function ModelsCell({ models }: { models?: RunModels }) {
  if (!hasRecordedModels(models)) {
    return <span className="muted">{emptyPlaceholder}</span>;
  }
  return (
    <div className="models-cell" title={modelSummaryText(models)}>
      {models?.attacker && <div><b>attacker</b><span>{models.attacker}</span></div>}
      {models?.target && <div><b>target</b><span>{models.target}</span></div>}
      {models?.judge && <div><b>judge</b><span>{models.judge}</span></div>}
    </div>
  );
}

function fallbackCopy(text: string): boolean {
  const node = document.createElement("textarea");
  node.value = text;
  node.style.position = "fixed";
  node.style.opacity = "0";
  document.body.appendChild(node);
  node.select();
  const ok = document.execCommand("copy");
  document.body.removeChild(node);
  return ok;
}

export function Runs() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [records, setRecords] = useState<RunRecord[]>([]);
  const [expanded, setExpanded] = useState<Set<number>>(() => new Set());
  const [copied, setCopied] = useState<string | null>(null);
  const [columns, setColumns] = useState<ColumnState[]>(() => DEFAULT_COLUMNS.map((column) => ({ ...column })));
  const [dragColumn, setDragColumn] = useState<ColumnId | null>(null);
  const [resizing, setResizing] = useState<{
    id: ColumnId;
    startX: number;
    startWidth: number;
  } | null>(null);

  const loadRuns = () => {
    setLoadError("");
    api.runs()
      .then((list) => { setRuns(list); setLoadError(""); })
      .catch((error) => { setRuns([]); setLoadError(error instanceof Error ? error.message : "Could not load run logs."); });
  };
  useEffect(() => { loadRuns(); }, []);

  // REL-14: Pointer Events with a pointercancel/blur fallback so a drag that ends
  // off-window still cleans up its listeners and the body cursor class.
  useEffect(() => {
    if (!resizing) return;
    const onMove = (ev: PointerEvent) => {
      const delta = ev.clientX - resizing.startX;
      setColumns((prev) => prev.map((column) => (
        column.id === resizing.id
          ? { ...column, width: Math.max(column.minWidth, resizing.startWidth + delta) }
          : column
      )));
    };
    const stop = () => setResizing(null);
    document.body.classList.add("is-resizing-column");
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    window.addEventListener("blur", stop);
    return () => {
      document.body.classList.remove("is-resizing-column");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      window.removeEventListener("blur", stop);
    };
  }, [resizing]);

  useEffect(() => {
    if (!open) {
      setRunDetail(null);
      setRecords([]);
      setExpanded(new Set());
      return;
    }
    // REL-5: stale-guard so switching to another run never lets the previous
    // run's (slower) response overwrite the newly-opened one.
    let active = true;
    setRunDetail(null);
    setRecords([]);
    setExpanded(new Set());
    api.run(open)
      .then((r) => {
        if (!active) return;
        setRunDetail(r);
        setRecords(r.records);
        setExpanded(new Set());
      })
      .catch(() => {
        if (!active) return;
        setRunDetail(null);
        setRecords([]);
        setExpanded(new Set());
      });
    return () => { active = false; };
  }, [open]);

  const toggleRow = (index: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const startColumnDrag = (id: ColumnId, ev: ReactDragEvent<HTMLTableCellElement>) => {
    if (resizing) {
      ev.preventDefault();
      return;
    }
    setDragColumn(id);
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", id);
  };

  const dropColumn = (id: ColumnId, ev: ReactDragEvent<HTMLTableCellElement>) => {
    ev.preventDefault();
    const source = (dragColumn || ev.dataTransfer.getData("text/plain")) as ColumnId | "";
    if (!source || source === id) {
      setDragColumn(null);
      return;
    }
    setColumns((prev) => reorderColumns(prev, source, id));
    setDragColumn(null);
  };

  const startColumnResize = (column: ColumnState, ev: ReactPointerEvent<HTMLButtonElement>) => {
    ev.preventDefault();
    ev.stopPropagation();
    try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* jsdom / unsupported */ }
    setResizing({ id: column.id, startX: ev.clientX, startWidth: column.width });
  };

  // A11Y-5: keyboard path for column resize — Arrow Left/Right nudge the width by
  // 12px (clamped to the column's minWidth), Home resets it to the default.
  const nudgeColumnWidth = (column: ColumnState, ev: ReactKeyboardEvent<HTMLButtonElement>) => {
    const STEP = 12;
    let delta = 0;
    if (ev.key === "ArrowLeft") delta = -STEP;
    else if (ev.key === "ArrowRight") delta = STEP;
    else if (ev.key === "Home") {
      const def = DEFAULT_COLUMNS.find((c) => c.id === column.id);
      if (def) { ev.preventDefault(); setColumns((prev) => prev.map((c) => c.id === column.id ? { ...c, width: def.width } : c)); }
      return;
    } else return;
    ev.preventDefault();
    setColumns((prev) => prev.map((c) => c.id === column.id
      ? { ...c, width: Math.max(c.minWidth, c.width + delta) }
      : c));
  };

  const copyText = async (key: string, text: string) => {
    if (!text) return;
    let copiedOk = false;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        copiedOk = true;
      } catch {
        copiedOk = false;
      }
    }
    if (!copiedOk) {
      try {
        copiedOk = fallbackCopy(text);
      } catch {
        copiedOk = false;
      }
    }
    if (copiedOk) {
      setCopied(key);
      window.setTimeout(() => setCopied((cur) => (cur === key ? null : cur)), 1400);
    } else {
      setCopied(null);
    }
  };

  // VIS-3: explicit loading / error / empty states (never a bare blank). An
  // error shows a Retry affordance instead of masquerading as "no run logs".
  if (loadError) return (
    <div className="async-error err" role="alert">
      <div className="async-error-msg">Could not load run logs: {loadError}</div>
      <button type="button" className="mini-btn" onClick={loadRuns}>Retry</button>
    </div>
  );
  if (!runs) return <div className="empty">Loading…</div>;
  if (!runs.length) return <div className="empty">No run logs in sessions/ yet.</div>;

  if (open) {
    return (
      <RunDetailView
        open={open}
        runDetail={runDetail}
        records={records}
        expanded={expanded}
        copied={copied}
        columns={columns}
        dragColumn={dragColumn}
        resizing={resizing}
        onBack={() => setOpen(null)}
        onToggleRow={toggleRow}
        onToggleAllExpanded={() => {
          const loaded = records.length;
          const allExpanded = loaded > 0 && expanded.size === loaded;
          setExpanded(allExpanded ? new Set() : new Set(records.map((_, index) => index)));
        }}
        onCopyText={copyText}
        onStartColumnDrag={startColumnDrag}
        onDropColumn={dropColumn}
        onStartColumnResize={startColumnResize}
        onNudgeColumnWidth={nudgeColumnWidth}
        onDragEnd={() => setDragColumn(null)}
      />
    );
  }

  return (
    <div className="card">
      <div className="section-title"><h2>{runs.length} run log{runs.length === 1 ? "" : "s"}</h2><div className="rule" /></div>
      <table>
        <thead><tr><th>Run</th><th>Time</th><th>Models</th><th>Records</th><th>Hits</th><th>Size</th></tr></thead>
        <tbody>
          {runs.map((r) => (
            /* A11Y-4: the run row opens the detail view — make it keyboard
               operable (focusable, role=button, Enter/Space) since it has no
               in-row button of its own. */
            <tr
              key={r.name}
              className="run-open-row"
              tabIndex={0}
              role="button"
              aria-label={`Open run ${r.name}`}
              onClick={() => setOpen(r.name)}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setOpen(r.name); } }}
            >
              <td className="mono">{r.name}</td>
              <td className="mono muted">{r.time || formatTimestamp(r.name)}</td>
              <td><ModelsCell models={r.models} /></td>
              <td className="mono">{r.records}</td>
              <td className={`mono ${r.hits ? "danger" : "muted"}`}>{r.hits}</td>
              <td className="mono muted">{fmtBytes(r.size)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
