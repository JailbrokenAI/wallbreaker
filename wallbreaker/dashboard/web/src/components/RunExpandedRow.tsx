import type { RunRecord } from "./RunDetailView";
import { emptyPlaceholder } from "../format";

// ── private helpers (mirrors the subset used here from RunDetailView.tsx) ─────

function textValue(v: unknown): string {
  if (typeof v === "string") return v;
  if (v == null) return "";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  try { return JSON.stringify(v, null, 2); } catch { return String(v); }
}

function objectValue(v: unknown): RunRecord | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as RunRecord) : null;
}

function jsonValue(v: unknown, pretty = true): string {
  try { return JSON.stringify(v, null, pretty ? 2 : 0) ?? textValue(v); } catch { return textValue(v); }
}

function fieldValue(v: unknown): string {
  return typeof v === "string" ? v : jsonValue(v);
}

function firstText(source: RunRecord | null, keys: string[]): string {
  if (!source) return "";
  for (const key of keys) {
    const value = textValue(source[key]).trim();
    if (value) return value;
  }
  return "";
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

// ── RunExpandedRow ────────────────────────────────────────────────────────────

export interface RunExpandedRowProps {
  record: RunRecord;
  index: number;
  lineNumber: number;
  lineKey: string;
  rawLine: string;
  colSpan: number;
  copied: string | null;
  rowKey: string;
  onCopyText: (key: string, text: string) => void;
}

export function RunExpandedRow({
  record,
  index,
  lineNumber,
  lineKey,
  rawLine,
  colSpan,
  copied,
  rowKey,
  onCopyText,
}: RunExpandedRowProps) {
  const fields = Object.entries(record);
  const fieldsText = fields
    .map(([key, value]) => `${key}:\n${fieldValue(value)}`)
    .join("\n\n");
  const fieldsKey = `${rowKey}-fields`;

  return (
    <tr className="run-expanded-row">
      <td colSpan={colSpan}>
        <div className="run-expanded-head">
          <span className="mono muted">record {index + 1} · line {lineNumber}</span>
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
        {textValue(record.kind).toLowerCase() === "inference" ? <InferenceExpanded record={record} /> : <div className="run-fields-panel">
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
  );
}
