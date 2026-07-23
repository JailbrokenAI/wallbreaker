import {
  Fragment,
  type DragEvent as ReactDragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { verdictKind, type RunDetail } from "../api";
import { emptyPlaceholder, formatTimestamp, snippet } from "../format";

// ── types shared with Runs.tsx ────────────────────────────────────────────────

export type RunRecord = Record<string, unknown>;
export type ColumnId = "index" | "ts" | "kind" | "verdict" | "technique" | "detail";

export interface RowDetail {
  prompt: string;
  response: string;
  reason: string;
}

export interface PreviewLine {
  label: string;
  value: string;
}

export interface ColumnState {
  id: ColumnId;
  label: string;
  width: number;
  minWidth: number;
}

export const DEFAULT_COLUMNS: ColumnState[] = [
  { id: "index", label: "#", width: 46, minWidth: 42 },
  { id: "ts", label: "time", width: 170, minWidth: 120 },
  { id: "kind", label: "kind", width: 120, minWidth: 90 },
  { id: "verdict", label: "verdict", width: 120, minWidth: 100 },
  { id: "technique", label: "technique", width: 170, minWidth: 120 },
  { id: "detail", label: "detail", width: 760, minWidth: 280 },
];

// ── helpers ───────────────────────────────────────────────────────────────────

export function textValue(v: unknown): string {
  if (typeof v === "string") return v;
  if (v == null) return "";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}

export function objectValue(v: unknown): RunRecord | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as RunRecord) : null;
}

export function jsonValue(v: unknown, pretty = true): string {
  try { return JSON.stringify(v, null, pretty ? 2 : 0) ?? textValue(v); } catch { return textValue(v); }
}

export function fieldValue(v: unknown): string {
  return typeof v === "string" ? v : jsonValue(v);
}

export function jsonlForRecords(records: RunRecord[]): string {
  return records.map((record) => jsonValue(record, false)).join("\n");
}

export function reorderColumns(columns: ColumnState[], source: ColumnId, target: ColumnId): ColumnState[] {
  const from = columns.findIndex((column) => column.id === source);
  const to = columns.findIndex((column) => column.id === target);
  if (from < 0 || to < 0 || from === to) return columns;
  const next = columns.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

function firstText(source: RunRecord | null, keys: string[]): string {
  if (!source) return "";
  for (const key of keys) {
    const value = textValue(source[key]).trim();
    if (value) return value;
  }
  return "";
}

export function detailForRecord(record: RunRecord): RowDetail {
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

export function previewForRecord(record: RunRecord, detail: RowDetail): PreviewLine[] {
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

// ── InferenceExpanded ─────────────────────────────────────────────────────────

function InferenceExpanded({ record }: { record: RunRecord }) {
  const request = objectValue(record.request) || {};
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

// ── RunDetailView — the open-run table view ───────────────────────────────────

export interface RunDetailViewProps {
  open: string;
  runDetail: RunDetail | null;
  records: RunRecord[];
  expanded: Set<number>;
  copied: string | null;
  columns: ColumnState[];
  dragColumn: ColumnId | null;
  resizing: { id: ColumnId; startX: number; startWidth: number } | null;
  onBack: () => void;
  onToggleRow: (index: number) => void;
  onToggleAllExpanded: () => void;
  onCopyText: (key: string, text: string) => void;
  onStartColumnDrag: (id: ColumnId, ev: ReactDragEvent<HTMLTableCellElement>) => void;
  onDropColumn: (id: ColumnId, ev: ReactDragEvent<HTMLTableCellElement>) => void;
  onStartColumnResize: (column: ColumnState, ev: ReactPointerEvent<HTMLButtonElement>) => void;
  onNudgeColumnWidth: (column: ColumnState, ev: ReactKeyboardEvent<HTMLButtonElement>) => void;
  onDragEnd: () => void;
}

export function RunDetailView({
  open,
  runDetail,
  records,
  expanded,
  copied,
  columns,
  dragColumn,
  resizing,
  onBack,
  onToggleRow,
  onToggleAllExpanded,
  onCopyText,
  onStartColumnDrag,
  onDropColumn,
  onStartColumnResize,
  onNudgeColumnWidth,
  onDragEnd,
}: RunDetailViewProps) {
  const loaded = records.length;
  const total = runDetail?.total ?? loaded;
  const loadedJsonl = runDetail?.raw_records?.join("\n") || jsonlForRecords(records);
  const allExpanded = loaded > 0 && expanded.size === loaded;

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
                  onClick={(ev) => { ev.stopPropagation(); onCopyText(lineKey, rawLine); }}
                >
                  {copied === lineKey ? "Copied" : "Copy line"}
                </button>
                <button
                  type="button"
                  className="mini-btn"
                  onClick={(ev) => { ev.stopPropagation(); onToggleRow(index); }}
                >
                  {isExpanded ? "Hide" : "View"}
                </button>
              </div>
            </div>
          </td>
        );
    }
  };

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
          onClick={onToggleAllExpanded}
        >
          {allExpanded ? "Collapse all" : "Expand all"}
        </button>
        <button
          type="button"
          className="mini-btn"
          disabled={!loadedJsonl}
          onClick={() => onCopyText(`${open}-jsonl`, loadedJsonl)}
        >
          {copied === `${open}-jsonl` ? "Copied" : "Copy JSONL"}
        </button>
        {/* A11Y-4: real <button> (was a <span onClick>) so it is focusable and
            operable with Enter/Space. */}
        <button type="button" className="chip" onClick={onBack}>← back</button>
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
                  onDragStart={(ev) => onStartColumnDrag(column.id, ev)}
                  onDragOver={(ev) => ev.preventDefault()}
                  onDrop={(ev) => onDropColumn(column.id, ev)}
                  onDragEnd={onDragEnd}
                >
                  <div className="run-th-content">
                    <span>{column.label}</span>
                    <button
                      type="button"
                      className="run-column-resize"
                      title="Drag to resize; arrow keys nudge width, Home resets"
                      aria-label={`Resize ${column.label} column`}
                      onPointerDown={(ev) => onStartColumnResize(column, ev)}
                      onKeyDown={(ev) => onNudgeColumnWidth(column, ev)}
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
                  onClick={() => onToggleRow(i)}
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
                            onClick={() => onCopyText(lineKey, rawLine)}
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
                            onClick={() => onCopyText(fieldsKey, fieldsText)}
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
                                  onClick={() => onCopyText(valueKey, valueText)}
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
                            onClick={() => onCopyText(lineKey, rawLine)}
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
