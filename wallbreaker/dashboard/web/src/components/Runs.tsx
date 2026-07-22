import {
  Fragment,
  useEffect,
  useState,
  type DragEvent as ReactDragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { api, verdictKind, type RunDetail, type RunModels, type RunSummary } from "../api";
import { emptyPlaceholder, formatTimestamp, snippet } from "../format";

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

  if (kind === "inference") {
    response = firstText(record, ["text"]);
    const request = objectValue(record.request);
    prompt = firstText(record, ["operation"]) || firstText(request, ["system"]);
  }

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
  if (kind === "inference") {
    const endpoint = objectValue(objectValue(record.request)?.endpoint);
    const stream = Array.isArray(record.stream) ? record.stream as RunRecord[] : [];
    const hasReasoning = stream.some((part) => textValue(part.channel) === "reasoning");
    return [
      { label: "Operation", value: firstText(record, ["operation"]) || "completion" },
      { label: "Model", value: firstText(endpoint, ["model", "name"]) || "unknown" },
      { label: "Status", value: firstText(record, ["status"]) || "incomplete" },
      { label: hasReasoning ? "Reasoning" : "Response", value: snippet(firstText(record, ["text"])) },
    ];
  }
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

function inferenceRequest(record: RunRecord): RunRecord {
  return objectValue(record.request) || {};
}

function InferenceExpanded({ record }: { record: RunRecord }) {
  const request = inferenceRequest(record);
  const endpoint = objectValue(request.endpoint);
  const messages = Array.isArray(request.messages) ? request.messages : [];
  const tools = request.tools;
  const stream = Array.isArray(record.stream) ? record.stream as RunRecord[] : [];
  return (
    <div className="inference-expanded">
      <section className="run-text-panel"><div className="run-text-head"><b>Request</b></div>
        <div className="inference-meta"><span><b>Operation</b>{firstText(record, ["operation"])}</span><span><b>Provider / model</b>{firstText(endpoint, ["provider", "name"])} · {firstText(endpoint, ["model"])}</span></div>
        {textValue(request.system) && <><b>System prompt</b><pre>{textValue(request.system)}</pre></>}
        <b>Messages</b><pre>{jsonValue(messages)}</pre>
        {tools != null && <><b>Tools and parameters</b><pre>{jsonValue({ tools, parameters: request.parameters })}</pre></>}
      </section>
      <section className="run-text-panel"><div className="run-text-head"><b>Stream transcript</b></div>
        {stream.length ? stream.map((part, index) => <div className={`inference-segment ${textValue(part.channel)}`} key={index}><strong>{textValue(part.channel) === "reasoning" ? "REASONING" : "MODEL"}</strong><pre>{textValue(part.text)}</pre></div>) : <span className="muted">No streamed text captured.</span>}
      </section>
      <section className="run-text-panel"><div className="run-text-head"><b>Completion</b></div>
        <div className="inference-meta"><span><b>Status</b>{firstText(record, ["status"])}</span><span><b>Duration</b>{firstText(record, ["duration_ms"])} ms</span><span><b>Stop</b>{textValue(record.stop_reasons) || "none"}</span></div>
        {textValue(record.error) && <pre className="inference-error">{textValue(record.error)}</pre>}
        <b>Final response</b><pre>{textValue(record.text) || emptyPlaceholder}</pre>
      </section>
    </div>
  );
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
  // 12px (clamped to the column's minWidth), Home resets it to the default. This
  // gives non-pointer users a way to size columns the drag handle otherwise
  // gated behind a mouse.
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
        const raw = textValue(record.ts);
        const ts = raw ? formatTimestamp(raw) : emptyPlaceholder;
        return <td key={column.id} className="mono muted clip" title={raw || ts}>{ts}</td>;
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
          {/* A11Y-4: real <button> (was a <span onClick>) so it is focusable and
              operable with Enter/Space. */}
          <button type="button" className="chip" onClick={() => setOpen(null)}>← back</button>
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
            {records.map((r, i) => {
              const detail = detailForRecord(r);
              const rowKey = `${open}-${i}`;
              const isExpanded = expanded.has(i);
              const sourceLines = Array.isArray(r.source_lines) ? r.source_lines as number[] : [];
              const rawMap = new Map((runDetail?.line_numbers || []).map((line, index) => [line, runDetail?.raw_records?.[index] || ""]));
              const rawLine = sourceLines.length ? sourceLines.map((line) => rawMap.get(line) || "").filter(Boolean).join("\n") : (runDetail?.raw_records?.[i] || jsonValue(r, false));
              const lineNumber = sourceLines[0] ?? runDetail?.line_numbers?.[i] ?? i + 1;
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
                        {textValue(r.kind).toLowerCase() === "inference" ? <InferenceExpanded record={r} /> : <div className="run-fields-panel">
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
                        </div>}
                        <details className="run-text-panel run-raw-panel">
                          <summary>Raw record</summary>
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
                        </details>
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
