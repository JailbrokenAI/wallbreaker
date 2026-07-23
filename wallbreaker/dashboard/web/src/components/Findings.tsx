import {
  Fragment,
  useEffect,
  useState,
  type DragEvent as ReactDragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { api, type Finding, type RunSummary } from "../api";
import { emptyPlaceholder } from "../format";
import {
  FindingExpanded, findingKey, modelsText, renderFindingCell,
  type FindingColumnId, type FindingColumnState as ColumnState,
} from "./FindingExpanded";

const DEFAULT_COLUMNS: ColumnState[] = [
  { id: "time", label: "time", width: 170, minWidth: 130 },
  { id: "run", label: "run", width: 220, minWidth: 150 },
  { id: "target", label: "target model", width: 240, minWidth: 160 },
  { id: "verdict", label: "verdict", width: 120, minWidth: 100 },
  { id: "technique", label: "technique", width: 170, minWidth: 120 },
  { id: "category", label: "category", width: 150, minWidth: 110 },
  { id: "payload", label: "payload", width: 520, minWidth: 240 },
  { id: "reason", label: "reason", width: 460, minWidth: 220 },
];

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function reorderColumns(columns: ColumnState[], source: FindingColumnId, target: FindingColumnId): ColumnState[] {
  const from = columns.findIndex((column) => column.id === source);
  const to = columns.findIndex((column) => column.id === target);
  if (from < 0 || to < 0 || from === to) return columns;
  const next = columns.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
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

export function Findings() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const [rows, setRows] = useState<Finding[] | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [openJudging, setOpenJudging] = useState<Set<string>>(() => new Set());
  const [copied, setCopied] = useState<string | null>(null);
  const [columns, setColumns] = useState<ColumnState[]>(() => DEFAULT_COLUMNS.map((column) => ({ ...column })));
  const [dragColumn, setDragColumn] = useState<FindingColumnId | null>(null);
  const [resizing, setResizing] = useState<{
    id: FindingColumnId;
    startX: number;
    startWidth: number;
  } | null>(null);

  const loadRuns = () => {
    setLoadError("");
    api.findingRuns()
      .then((list) => {
        setRuns(list);
        setLoadError("");
        const firstWithFindings = list.find((run) => (run.findings ?? run.hits) > 0);
        const first = firstWithFindings || list[0];
        setSelectedRuns(first ? [first.name] : []);
      })
      .catch((error) => {
        setRuns([]);
        setSelectedRuns([]);
        setLoadError(error instanceof Error ? error.message : "Could not load findings.");
      });
  };
  useEffect(() => { loadRuns(); }, []);

  useEffect(() => {
    if (runs === null) return;
    // REL-5: stale-guard so a superseded selectedRuns fetch never overwrites the
    // rows for the current selection.
    let active = true;
    setRows(null);
    setExpanded(new Set());
    setOpenJudging(new Set());
    if (!selectedRuns.length) {
      setRows([]);
      return;
    }
    api.findings(selectedRuns)
      .then((v) => { if (active) setRows(v); })
      .catch(() => { if (active) setRows([]); });
    return () => { active = false; };
  }, [runs, selectedRuns]);

  // REL-14: use Pointer Events with a pointercancel/blur fallback so a drag that
  // ends off-window (or is interrupted) still tears down its listeners and the
  // body cursor class — the old mouseup-only cleanup could leak.
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

  const toggleRun = (name: string) => {
    setSelectedRuns((prev) => (
      prev.includes(name) ? prev.filter((item) => item !== name) : [...prev, name]
    ));
  };

  const toggleRow = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleJudging = (key: string) => {
    setOpenJudging((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const startColumnDrag = (id: FindingColumnId, ev: ReactDragEvent<HTMLTableCellElement>) => {
    if (resizing) {
      ev.preventDefault();
      return;
    }
    setDragColumn(id);
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", id);
  };

  const dropColumn = (id: FindingColumnId, ev: ReactDragEvent<HTMLTableCellElement>) => {
    ev.preventDefault();
    const source = (dragColumn || ev.dataTransfer.getData("text/plain")) as FindingColumnId | "";
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
    // setPointerCapture keeps move/up events flowing to the handle even if the
    // pointer leaves the window during the drag (REL-14).
    try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* jsdom / unsupported */ }
    setResizing({ id: column.id, startX: ev.clientX, startWidth: column.width });
  };

  // A11Y-5: keyboard resize — Arrow Left/Right nudge width by 12px (clamped to
  // minWidth), Home resets to the column default, so the drag-only handle also
  // works without a pointer.
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
    }
  };

  // VIS-3: explicit loading / error / empty states — an error surfaces a Retry
  // affordance instead of silently rendering "no run logs".
  if (loadError) return (
    <div className="async-error err" role="alert">
      <div className="async-error-msg">Could not load findings: {loadError}</div>
      <button type="button" className="mini-btn" onClick={loadRuns}>Retry</button>
    </div>
  );
  if (!runs || !rows) return <div className="empty">Loading…</div>;
  if (!runs.length) return <div className="empty">No run logs in sessions/ yet.</div>;

  const selectedSet = new Set(selectedRuns);
  const allFindingRuns = runs.filter((run) => (run.findings ?? run.hits) > 0).map((run) => run.name);
  const allExpanded = rows.length > 0 && expanded.size === rows.length;

  return (
    <div className="findings-layout">
      <div className="card findings-picker">
        <div className="section-title">
          <h2>Run selection</h2>
          <div className="rule" />
        </div>
        <div className="run-actions findings-picker-actions">
          <button type="button" className="mini-btn" onClick={() => setSelectedRuns(allFindingRuns)}>
            Select runs with findings
          </button>
          <button type="button" className="mini-btn" onClick={() => setSelectedRuns(runs[0] ? [runs[0].name] : [])}>
            Latest run
          </button>
          <button type="button" className="mini-btn" onClick={() => setSelectedRuns([])}>
            Clear
          </button>
        </div>
        <div className="finding-run-list">
          {runs.map((run) => {
            const selected = selectedSet.has(run.name);
            const count = run.findings ?? run.hits;
            return (
              <button
                type="button"
                key={run.name}
                className={`finding-run-option ${selected ? "selected" : ""}`}
                onClick={() => toggleRun(run.name)}
                title={modelsText(run.models)}
              >
                <span className="mono">{run.name}</span>
                <span className="muted mono">{run.time || "unknown time"}</span>
                <span className="muted mono">target: {run.models?.target || emptyPlaceholder}</span>
                <span className={`badge ${count ? "bypass" : "neutral"}`}>{count} finding{count === 1 ? "" : "s"}</span>
                <span className="muted mono">{run.records} records | {fmtBytes(run.size)}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="card findings-results">
        <div className="section-title">
          <h2>{rows.length} finding{rows.length === 1 ? "" : "s"}</h2>
          <div className="rule" />
          <span className="muted mono">{selectedRuns.length} run{selectedRuns.length === 1 ? "" : "s"} selected</span>
          <button
            type="button"
            className="mini-btn"
            disabled={!rows.length}
            onClick={() => setExpanded(allExpanded ? new Set() : new Set(rows.map(findingKey)))}
          >
            {allExpanded ? "Collapse all" : "Expand all"}
          </button>
        </div>
        {!selectedRuns.length && <div className="empty">Select one or more runs to inspect findings.</div>}
        {!!selectedRuns.length && !rows.length && <div className="empty">No COMPLIED / PARTIAL findings in the selected run logs.</div>}
        {!!rows.length && (
          <div className="runs-table-wrap">
            <table className="runs-table findings-table" style={{ minWidth: columns.reduce((sum, column) => sum + column.width, 0) }}>
              <colgroup>
                {columns.map((column) => <col key={column.id} style={{ width: column.width }} />)}
              </colgroup>
              <thead>
                <tr>
                  {columns.map((column) => (
                    <th
                      key={column.id}
                      className={`run-col-header ${dragColumn === column.id ? "dragging" : ""}`}
                      draggable={!resizing}
                      onDragStart={(ev) => startColumnDrag(column.id, ev)}
                      onDragOver={(ev) => ev.preventDefault()}
                      onDrop={(ev) => dropColumn(column.id, ev)}
                      onDragEnd={() => setDragColumn(null)}
                    >
                      <div className="run-th-content">
                        <span>{column.label}</span>
                        <button
                          type="button"
                          className="run-column-resize"
                          title="Drag to resize; arrow keys nudge width, Home resets"
                          aria-label={`Resize ${column.label} column`}
                          onPointerDown={(ev) => startColumnResize(column, ev)}
                          onKeyDown={(ev) => nudgeColumnWidth(column, ev)}
                          onClick={(ev) => ev.stopPropagation()}
                          draggable={false}
                        />
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((finding, index) => {
                  const key = findingKey(finding, index);
                  const isExpanded = expanded.has(key);
                  return (
                    <Fragment key={key}>
                      <tr
                        className={`run-record-row ${isExpanded ? "expanded" : ""}`}
                        onClick={() => toggleRow(key)}
                      >
                        {columns.map((column) => renderFindingCell(column, finding, key, copied, copyText))}
                      </tr>
                      {isExpanded && (
                        <FindingExpanded
                          finding={finding}
                          rowKey={key}
                          colSpan={columns.length}
                          copied={copied}
                          judgingOpen={openJudging.has(key)}
                          onCopy={copyText}
                          onToggleJudging={() => toggleJudging(key)}
                        />
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
