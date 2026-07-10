import {
  Fragment,
  useEffect,
  useState,
  type DragEvent as ReactDragEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { api, verdictKind, type RunDetail, type RunModels, type RunSummary } from "../api";

type RunRecord = Record<string, unknown>;
type ColumnId = "index" | "ts" | "kind" | "verdict" | "technique" | "detail";

interface RowDetail {
  prompt: string;
  response: string;
  reason: string;
}

interface PreviewLine {
  label: string;
  value: string;
}

interface ColumnState {
  id: ColumnId;
  label: string;
  width: number;
  minWidth: number;
}

const DEFAULT_COLUMNS: ColumnState[] = [
  { id: "index", label: "#", width: 46, minWidth: 42 },
  { id: "ts", label: "time", width: 170, minWidth: 120 },
  { id: "kind", label: "kind", width: 120, minWidth: 90 },
  { id: "verdict", label: "verdict", width: 120, minWidth: 100 },
  { id: "technique", label: "technique", width: 170, minWidth: 120 },
  { id: "detail", label: "detail", width: 760, minWidth: 280 },
];

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function timeFromRunName(name: string): string {
  const match = /^run-(\d{8})-?(\d{6})\.jsonl$/.exec(name);
  if (!match) return "";
  const stamp = `${match[1]}${match[2]}`;
  const year = Number(stamp.slice(0, 4));
  const month = Number(stamp.slice(4, 6));
  const day = Number(stamp.slice(6, 8));
  const hour = Number(stamp.slice(8, 10));
  const minute = Number(stamp.slice(10, 12));
  const second = Number(stamp.slice(12, 14));
  const valid =
    month >= 1 && month <= 12 &&
    day >= 1 && day <= 31 &&
    hour <= 23 &&
    minute <= 59 &&
    second <= 59;
  if (!valid) return "";
  return `${year.toString().padStart(4, "0")}-${stamp.slice(4, 6)}-${stamp.slice(6, 8)} ${stamp.slice(8, 10)}:${stamp.slice(10, 12)}:${stamp.slice(12, 14)}`;
}

function hasRecordedModels(models: RunModels | undefined): boolean {
  return !!models?.recorded && !!(models.attacker || models.target || models.judge);
}

function modelSummaryText(models: RunModels | undefined): string {
  if (!hasRecordedModels(models)) return "not recorded";
  return [
    models?.attacker ? `attacker: ${models.attacker}` : "",
    models?.target ? `target: ${models.target}` : "",
    models?.judge ? `judge: ${models.judge}` : "",
  ].filter(Boolean).join("\n");
}

function ModelsCell({ models }: { models?: RunModels }) {
  if (!hasRecordedModels(models)) {
    return <span className="muted">not recorded</span>;
  }
  return (
    <div className="models-cell" title={modelSummaryText(models)}>
      {models?.attacker && <div><b>attacker</b><span>{models.attacker}</span></div>}
      {models?.target && <div><b>target</b><span>{models.target}</span></div>}
      {models?.judge && <div><b>judge</b><span>{models.judge}</span></div>}
    </div>
  );
}

function objectValue(v: unknown): RunRecord | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as RunRecord) : null;
}

function textValue(v: unknown): string {
  if (typeof v === "string") return v;
  if (v == null) return "";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

function firstText(source: RunRecord | null, keys: string[]): string {
  if (!source) return "";
  for (const key of keys) {
    const value = textValue(source[key]).trim();
    if (value) return value;
  }
  return "";
}

function jsonValue(v: unknown, pretty = true): string {
  try {
    return JSON.stringify(v, null, pretty ? 2 : 0) ?? textValue(v);
  } catch {
    return textValue(v);
  }
}

function fieldValue(v: unknown): string {
  return typeof v === "string" ? v : jsonValue(v);
}

function detailForRecord(record: RunRecord): RowDetail {
  const kind = textValue(record.kind).toLowerCase();
  const args = objectValue(record.args) || objectValue(record.input);

  let prompt = firstText(record, ["payload", "prompt", "request", "query"]);
  let response = firstText(record, ["response", "content", "result", "answer", "output"]);

  if (kind === "user" || kind === "objective") {
    prompt = firstText(record, ["text", "payload", "prompt", "request"]) || prompt;
  } else if (kind === "assistant") {
    response = firstText(record, ["text", "response", "content"]) || response;
  } else if (kind === "tool_call") {
    prompt = firstText(args, ["prompt", "request", "payload", "text", "objective", "query"]) || prompt;
  } else if (kind === "tool_result") {
    response = firstText(record, ["content", "response", "text"]) || response;
  }

  return {
    prompt,
    response,
    reason: firstText(record, ["reason", "rationale", "error"]),
  };
}

function previewForRecord(record: RunRecord, detail: RowDetail): PreviewLine[] {
  const kind = textValue(record.kind).toLowerCase();
  const args = objectValue(record.args) || objectValue(record.input);
  if (kind === "tool_call") {
    return [
      { label: "Tool", value: firstText(record, ["tool", "name"]) || "tool_call" },
      { label: "Args", value: args ? jsonValue(args) : firstText(record, ["args", "input"]) },
    ];
  }
  if (kind === "tool_result") {
    return [
      { label: "Tool", value: firstText(record, ["tool", "name"]) || "tool_result" },
      { label: firstText(record, ["error"]) === "true" ? "Error" : "Result", value: detail.response },
    ];
  }
  if (detail.prompt || detail.response) {
    return [
      { label: "Prompt", value: detail.prompt },
      { label: "Response", value: detail.response },
    ];
  }
  const fields = Object.entries(record).filter(([key]) => key !== "ts" && key !== "kind");
  return fields.slice(0, 2).map(([key, value]) => ({ label: key, value: textValue(value) }));
}

function snippet(value: string): string {
  const compact = value.replace(/\s+/g, " ").trim();
  if (!compact) return "Not recorded";
  return compact.length > 180 ? `${compact.slice(0, 180)}...` : compact;
}

function jsonlForRecords(records: RunRecord[]): string {
  return records.map((record) => jsonValue(record, false)).join("\n");
}

function reorderColumns(columns: ColumnState[], source: ColumnId, target: ColumnId): ColumnState[] {
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

export function Runs() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
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

  useEffect(() => { api.runs().then(setRuns).catch(() => setRuns([])); }, []);

  useEffect(() => {
    if (!resizing) return;
    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - resizing.startX;
      setColumns((prev) => prev.map((column) => (
        column.id === resizing.id
          ? { ...column, width: Math.max(column.minWidth, resizing.startWidth + delta) }
          : column
      )));
    };
    const onUp = () => setResizing(null);
    document.body.classList.add("is-resizing-column");
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      document.body.classList.remove("is-resizing-column");
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [resizing]);

  useEffect(() => {
    if (!open) {
      setRunDetail(null);
      setRecords([]);
      setExpanded(new Set());
      return;
    }
    setRunDetail(null);
    setRecords([]);
    setExpanded(new Set());
    api.run(open)
      .then((r) => {
        setRunDetail(r);
        setRecords(r.records);
        setExpanded(new Set());
      })
      .catch(() => {
        setRunDetail(null);
        setRecords([]);
        setExpanded(new Set());
      });
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

  const startColumnResize = (column: ColumnState, ev: ReactMouseEvent<HTMLSpanElement>) => {
    ev.preventDefault();
    ev.stopPropagation();
    setResizing({ id: column.id, startX: ev.clientX, startWidth: column.width });
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

  const renderRunCell = (
    column: ColumnState,
    record: RunRecord,
    index: number,
    preview: PreviewLine[],
    isExpanded: boolean,
    rawLine: string,
    lineKey: string,
  ) => {
    const label = textValue(record.label);
    switch (column.id) {
      case "index":
        return <td key={column.id} className="muted">{index + 1}</td>;
      case "ts": {
        const ts = textValue(record.ts);
        return <td key={column.id} className="mono muted clip" title={ts}>{ts}</td>;
      }
      case "kind":
        return <td key={column.id} className="mono muted">{textValue(record.kind)}</td>;
      case "verdict":
        return (
          <td key={column.id}>
            {label ? <span className={`badge ${verdictKind(label)}`}>{label}</span> : ""}
          </td>
        );
      case "technique":
        return <td key={column.id} className="mono clip" title={textValue(record.technique)}>{textValue(record.technique)}</td>;
      case "detail":
        return (
          <td key={column.id}>
            <div className="run-detail-cell">
              <div className="run-detail-preview">
                {preview.length ? preview.map((line, lineIndex) => (
                  <div key={`${line.label}-${lineIndex}`}>
                    <b>{line.label}</b>
                    <span title={line.value}>{snippet(line.value)}</span>
                  </div>
                )) : (
                  <div><b>Record</b><span title={rawLine}>{snippet(rawLine)}</span></div>
                )}
              </div>
              <div className="run-actions">
                <button
                  type="button"
                  className="mini-btn"
                  onClick={(ev) => { ev.stopPropagation(); copyText(lineKey, rawLine); }}
                >
                  {copied === lineKey ? "Copied" : "Copy line"}
                </button>
                <button
                  type="button"
                  className="mini-btn"
                  onClick={(ev) => { ev.stopPropagation(); toggleRow(index); }}
                >
                  {isExpanded ? "Hide" : "View"}
                </button>
              </div>
            </div>
          </td>
        );
    }
  };

  if (!runs) return <div className="empty">Loading…</div>;
  if (!runs.length) return <div className="empty">No run logs in sessions/ yet.</div>;

  if (open) {
    const loaded = records.length;
    const total = runDetail?.total ?? loaded;
    const loadedJsonl = runDetail?.raw_records?.join("\n") || jsonlForRecords(records);
    const allExpanded = loaded > 0 && expanded.size === loaded;
    return (
      <div className="card">
        <div className="section-title">
          <h2 className="mono">{open}</h2>
          <div className="rule" />
          <span className="muted mono">{loaded}{total !== loaded ? ` of ${total}` : ""} records</span>
          <button
            type="button"
            className="mini-btn"
            disabled={!records.length}
            onClick={() => setExpanded(allExpanded ? new Set() : new Set(records.map((_, index) => index)))}
          >
            {allExpanded ? "Collapse all" : "Expand all"}
          </button>
          <button
            type="button"
            className="mini-btn"
            disabled={!loadedJsonl}
            onClick={() => copyText(`${open}-jsonl`, loadedJsonl)}
          >
            {copied === `${open}-jsonl` ? "Copied" : "Copy JSONL"}
          </button>
          <span className="chip" onClick={() => setOpen(null)}>← back</span>
        </div>
        <div className="runs-table-wrap">
          <table className="runs-table" style={{ minWidth: columns.reduce((sum, column) => sum + column.width, 0) }}>
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
                      <span
                        className="run-column-resize"
                        title="Drag to resize"
                        onMouseDown={(ev) => startColumnResize(column, ev)}
                      />
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
            {records.map((r, i) => {
              const detail = detailForRecord(r);
              const rowKey = `${open}-${i}`;
              const isExpanded = expanded.has(i);
              const rawLine = runDetail?.raw_records?.[i] || jsonValue(r, false);
              const lineNumber = runDetail?.line_numbers?.[i] ?? i + 1;
              const lineKey = `${rowKey}-line`;
              const fields = Object.entries(r);
              const fieldsText = fields
                .map(([key, value]) => `${key}:\n${fieldValue(value)}`)
                .join("\n\n");
              const fieldsKey = `${rowKey}-fields`;
              const preview = previewForRecord(r, detail);
              return (
                <Fragment key={rowKey}>
                  <tr
                    className={`run-record-row ${isExpanded ? "expanded" : ""}`}
                    onClick={() => toggleRow(i)}
                  >
                    {columns.map((column) => renderRunCell(column, r, i, preview, isExpanded, rawLine, lineKey))}
                  </tr>
                  {isExpanded && (
                    <tr className="run-expanded-row">
                      <td colSpan={columns.length}>
                        <div className="run-expanded-head">
                          <span className="mono muted">record {i + 1} · line {lineNumber}</span>
                          <div className="run-actions">
                            <button
                              type="button"
                              className="mini-btn"
                              onClick={() => copyText(lineKey, rawLine)}
                            >
                              {copied === lineKey ? "Copied" : "Copy JSONL line"}
                            </button>
                          </div>
                        </div>
                        <div className="run-fields-panel">
                          <div className="run-text-head">
                            <b>All JSON fields</b>
                            <button
                              type="button"
                              className="mini-btn"
                              onClick={() => copyText(fieldsKey, fieldsText)}
                            >
                              {copied === fieldsKey ? "Copied" : "Copy fields"}
                            </button>
                          </div>
                          <div className="run-field-list">
                            {fields.map(([key, value]) => {
                              const valueText = fieldValue(value);
                              const valueKey = `${rowKey}-field-${key}`;
                              return (
                                <div className="run-field-row" key={key}>
                                  <div className="run-field-key mono">{key}</div>
                                  <pre>{valueText}</pre>
                                  <button
                                    type="button"
                                    className="mini-btn"
                                    onClick={() => copyText(valueKey, valueText)}
                                  >
                                    {copied === valueKey ? "Copied" : "Copy"}
                                  </button>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                        <div className="run-text-panel run-raw-panel">
                          <div className="run-text-head">
                            <b>Raw JSONL line</b>
                            <button
                              type="button"
                              className="mini-btn"
                              onClick={() => copyText(lineKey, rawLine)}
                            >
                              {copied === lineKey ? "Copied" : "Copy"}
                            </button>
                          </div>
                          <pre>{rawLine}</pre>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="section-title"><h2>{runs.length} run log{runs.length === 1 ? "" : "s"}</h2><div className="rule" /></div>
      <table>
        <thead><tr><th>Run</th><th>Time</th><th>Models</th><th>Records</th><th>Hits</th><th>Size</th></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.name} style={{ cursor: "pointer" }} onClick={() => setOpen(r.name)}>
              <td className="mono">{r.name}</td>
              <td className="mono muted">{r.time || timeFromRunName(r.name) || "unknown"}</td>
              <td><ModelsCell models={r.models} /></td>
              <td className="mono">{r.records}</td>
              <td className="mono" style={{ color: r.hits ? "var(--bad)" : "var(--muted)" }}>{r.hits}</td>
              <td className="mono muted">{fmtBytes(r.size)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
