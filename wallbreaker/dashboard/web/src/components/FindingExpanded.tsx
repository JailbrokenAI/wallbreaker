import { verdictKind, type Finding, type RunModels } from "../api";
import { emptyPlaceholder, formatTimestamp, snippet } from "../format";

function textValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function jsonValue(value: unknown, pretty = true): string {
  try {
    return JSON.stringify(value, null, pretty ? 2 : 0) ?? textValue(value);
  } catch {
    return textValue(value);
  }
}

function chainText(chain: string[] | undefined): string {
  return chain?.length ? chain.join(" + ") : "none recorded";
}

export function modelsText(models: RunModels | undefined): string {
  if (!models?.recorded) return emptyPlaceholder;
  return [
    models.attacker ? `attacker: ${models.attacker}` : "",
    models.target ? `target: ${models.target}` : "",
    models.judge ? `judge: ${models.judge}` : "",
  ].filter(Boolean).join("\n") || emptyPlaceholder;
}

export function findingKey(finding: Finding, index: number): string {
  return finding.id || `${finding.run || "run"}:${finding.line || index}`;
}

export function TextPanel({
  title,
  value,
  copyKey,
  copied,
  onCopy,
}: {
  title: string;
  value: string;
  copyKey: string;
  copied: string | null;
  onCopy: (key: string, text: string) => void;
}) {
  return (
    <div className="run-text-panel">
      <div className="run-text-head">
        <b>{title}</b>
        <button type="button" className="mini-btn" disabled={!value} onClick={() => onCopy(copyKey, value)}>
          {copied === copyKey ? "Copied" : "Copy"}
        </button>
      </div>
      {value ? <pre>{value}</pre> : <div className="empty-inline">Not recorded</div>}
    </div>
  );
}

export function FindingExpanded({
  finding,
  rowKey,
  colSpan,
  copied,
  judgingOpen,
  onCopy,
  onToggleJudging,
}: {
  finding: Finding;
  rowKey: string;
  colSpan: number;
  copied: string | null;
  judgingOpen: boolean;
  onCopy: (key: string, text: string) => void;
  onToggleJudging: () => void;
}) {
  const technique = finding.technique_detail || {};
  const fields = finding.fields || {};
  const fieldEntries = Object.entries(fields);
  const fieldText = fieldEntries.map(([key, value]) => `${key}:\n${textValue(value)}`).join("\n\n");
  const rawLine = finding.raw || jsonValue(fields, false);
  const judging = finding.judging || {};
  const criteriaText = [
    judging.criteria ? `CRITERIA\n${judging.criteria}` : "",
    judging.template ? `TEMPLATE\n${judging.template}` : "",
  ].filter(Boolean).join("\n\n");

  return (
    <tr className="run-expanded-row finding-expanded-row">
      <td colSpan={colSpan}>
        <div className="run-expanded-head">
          <span className="mono muted">
            {finding.run || "run"} | line {finding.line ?? "-"} | {finding.ts || finding.run_time || "unknown time"}
          </span>
          <div className="run-actions">
            <button type="button" className="mini-btn" onClick={() => onCopy(`${rowKey}-raw`, rawLine)}>
              {copied === `${rowKey}-raw` ? "Copied" : "Copy raw"}
            </button>
          </div>
        </div>

        <div className="finding-expanded-grid">
          <TextPanel title="Payload" value={textValue(finding.payload)} copyKey={`${rowKey}-payload-full`} copied={copied} onCopy={onCopy} />
          <TextPanel title="Response" value={textValue(finding.response)} copyKey={`${rowKey}-response`} copied={copied} onCopy={onCopy} />
          <TextPanel title="Reason" value={textValue(finding.reason)} copyKey={`${rowKey}-reason`} copied={copied} onCopy={onCopy} />

          <div className="run-fields-panel finding-tech-panel">
            <div className="run-text-head">
              <b>Technique and obfuscation</b>
              <button type="button" className="mini-btn" onClick={() => onCopy(`${rowKey}-technique`, jsonValue(technique))}>
                {copied === `${rowKey}-technique` ? "Copied" : "Copy"}
              </button>
            </div>
            <div className="finding-kv-list">
              <div><b>Technique</b><span className="mono">{technique.technique || finding.technique || "manual"}</span></div>
              <div><b>Source tool</b><span className="mono">{technique.source_tool || emptyPlaceholder}</span></div>
              <div><b>Preset</b><span className="mono">{technique.preset || "none recorded"}</span></div>
              <div><b>Prompt chain</b><span className="mono">{chainText(technique.transforms?.prompt)}</span></div>
              <div><b>System chain</b><span className="mono">{chainText(technique.transforms?.system)}</span></div>
              <div><b>Response chain</b><span className="mono">{chainText(technique.transforms?.response)}</span></div>
              <div><b>Think seed</b><span className="mono">{technique.think_seed || "none recorded"}</span></div>
              <div><b>Max tokens</b><span className="mono">{textValue(technique.max_tokens) || emptyPlaceholder}</span></div>
            </div>
            <div className="finding-subpanel">
              <b>Template / instructions</b>
              <pre>{technique.template || technique.instructions || "Not recorded in this run log."}</pre>
            </div>
            {!!technique.raw_args && Object.keys(technique.raw_args).length > 0 && (
              <div className="finding-subpanel">
                <b>Tool arguments</b>
                <pre>{jsonValue(technique.raw_args)}</pre>
              </div>
            )}
          </div>

          <div className="run-fields-panel finding-conversation-panel">
            <div className="run-text-head">
              <b>Full conversation history</b>
              <button type="button" className="mini-btn" onClick={() => onCopy(`${rowKey}-conversation`, jsonValue(finding.conversation || []))}>
                {copied === `${rowKey}-conversation` ? "Copied" : "Copy"}
              </button>
            </div>
            <div className="finding-conversation">
              {finding.conversation?.length ? finding.conversation.map((turn, index) => (
                <div key={`${turn.role}-${index}`} className={`finding-turn ${turn.role}`}>
                  <div className="finding-turn-head">
                    <span className="mono">{turn.role}</span>
                    {turn.source && <span className="muted mono">{turn.source}</span>}
                  </div>
                  <pre>{turn.content}</pre>
                </div>
              )) : <div className="empty-inline">No conversation turns were recorded for this finding.</div>}
            </div>
          </div>

          <div className="run-fields-panel finding-judging-panel">
            <div className="run-text-head">
              <b>Judging</b>
              <div className="run-actions">
                <button type="button" className="mini-btn" onClick={() => onCopy(`${rowKey}-judging`, jsonValue(judging))}>
                  {copied === `${rowKey}-judging` ? "Copied" : "Copy"}
                </button>
                <button type="button" className="mini-btn" onClick={onToggleJudging}>
                  {judgingOpen ? "Hide criteria" : "Show criteria"}
                </button>
              </div>
            </div>
            <div className="finding-kv-list compact">
              <div><b>Source</b><span className="mono">{judging.source || "judge"}</span></div>
              <div><b>Label</b><span className="mono">{judging.label || finding.label}</span></div>
              <div><b>Score</b><span className="mono">{textValue(judging.score) || "not recorded"}</span></div>
              <div><b>Reason</b><span>{judging.reason || finding.reason || "not recorded"}</span></div>
            </div>
            {judgingOpen && <pre>{criteriaText || "No judging criteria were recorded."}</pre>}
          </div>

          <div className="run-fields-panel finding-fields-panel">
            <div className="run-text-head">
              <b>All JSON fields</b>
              <button type="button" className="mini-btn" onClick={() => onCopy(`${rowKey}-fields`, fieldText)}>
                {copied === `${rowKey}-fields` ? "Copied" : "Copy fields"}
              </button>
            </div>
            <div className="run-field-list">
              {fieldEntries.map(([key, value]) => {
                const valueText = textValue(value);
                const valueKey = `${rowKey}-field-${key}`;
                return (
                  <div className="run-field-row" key={key}>
                    <div className="run-field-key mono">{key}</div>
                    <pre>{valueText}</pre>
                    <button type="button" className="mini-btn" onClick={() => onCopy(valueKey, valueText)}>
                      {copied === valueKey ? "Copied" : "Copy"}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="run-text-panel run-raw-panel finding-raw-panel">
            <div className="run-text-head">
              <b>Raw JSONL line</b>
              <button type="button" className="mini-btn" onClick={() => onCopy(`${rowKey}-raw`, rawLine)}>
                {copied === `${rowKey}-raw` ? "Copied" : "Copy"}
              </button>
            </div>
            <pre>{rawLine}</pre>
          </div>
        </div>
      </td>
    </tr>
  );
}

// Re-export snippet so Findings.tsx can import it from here (avoids a direct format.ts import loop)
export { snippet };

// ── FindingCell — stateless cell renderer used by Findings table ──────────────

export type FindingColumnId = "time" | "run" | "target" | "verdict" | "technique" | "category" | "payload" | "reason";

export interface FindingColumnState {
  id: FindingColumnId;
  label: string;
  width: number;
  minWidth: number;
}

function textValueLocal(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

export function renderFindingCell(
  column: FindingColumnState,
  finding: Finding,
  key: string,
  copied: string | null,
  onCopy: (key: string, text: string) => void,
): React.ReactNode {
  switch (column.id) {
    case "time": {
      const raw = finding.ts || finding.run_time || "";
      const time = raw ? formatTimestamp(raw) : emptyPlaceholder;
      return <td key={column.id} className="mono muted clip" title={raw || time}>{time}</td>;
    }
    case "run":
      return <td key={column.id} className="mono clip" title={finding.run}>{finding.run || "latest"}</td>;
    case "target": {
      const target = finding.models?.target || textValueLocal(finding.target_model) || emptyPlaceholder;
      return <td key={column.id} className="mono clip" title={target}>{target}</td>;
    }
    case "verdict":
      return (
        <td key={column.id}>
          <span className={`badge ${verdictKind(finding.label)}`}>{finding.label}</span>
        </td>
      );
    case "technique":
      return <td key={column.id} className="mono clip" title={finding.technique}>{finding.technique ?? "manual"}</td>;
    case "category":
      return <td key={column.id} className="mono muted clip" title={finding.category}>{finding.category ?? emptyPlaceholder}</td>;
    case "payload":
      return (
        <td key={column.id}>
          <div className="finding-cell-main">
            <span className="mono clip" title={finding.payload}>{snippet(finding.payload, 260)}</span>
            <button
              type="button"
              className="mini-btn"
              onClick={(ev) => { ev.stopPropagation(); onCopy(`${key}-payload`, textValueLocal(finding.payload)); }}
              disabled={!finding.payload}
            >
              {copied === `${key}-payload` ? "Copied" : "Copy"}
            </button>
          </div>
        </td>
      );
    case "reason":
      return <td key={column.id} className="muted clip" title={finding.reason}>{snippet(finding.reason, 240)}</td>;
  }
}
