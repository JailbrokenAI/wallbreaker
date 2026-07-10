import {
  Fragment,
  useEffect,
  useState,
  type DragEvent as ReactDragEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { api, verdictKind, type Finding, type RunModels, type RunSummary } from "../api";

type FindingColumnId = "time" | "run" | "verdict" | "technique" | "category" | "payload" | "reason";

interface ColumnState {
  id: FindingColumnId;
  label: string;
  width: number;
  minWidth: number;
}

const DEFAULT_COLUMNS: ColumnState[] = [
  { id: "time", label: "time", width: 170, minWidth: 130 },
  { id: "run", label: "run", width: 220, minWidth: 150 },
  { id: "verdict", label: "verdict", width: 120, minWidth: 100 },
  { id: "technique", label: "technique", width: 170, minWidth: 120 },
  { id: "category", label: "category", width: 150, minWidth: 110 },
  { id: "payload", label: "payload", width: 520, minWidth: 240 },
  { id: "reason", label: "reason", width: 460, minWidth: 220 },
];

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

function snippet(value: unknown, len = 180): string {
  const compact = textValue(value).replace(/\s+/g, " ").trim();
  if (!compact) return "Not recorded";
  return compact.length > len ? `${compact.slice(0, len)}...` : compact;
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function findingKey(finding: Finding, index: number): string {
  return finding.id || `${finding.run || "run"}:${finding.line || index}`;
}

function chainText(chain: string[] | undefined): string {
  return chain?.length ? chain.join(" + ") : "none recorded";
}

function modelsText(models: RunModels | undefined): string {
  if (!models?.recorded) return "not recorded";
  return [
    models.attacker ? `attacker: ${models.attacker}` : "",
    models.target ? `target: ${models.target}` : "",
    models.judge ? `judge: ${models.judge}` : "",
  ].filter(Boolean).join("\n") || "not recorded";
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

  useEffect(() => {
    api.findingRuns()
      .then((list) => {
        setRuns(list);
        const firstWithFindings = list.find((run) => (run.findings ?? run.hits) > 0);
        const first = firstWithFindings || list[0];
        setSelectedRuns(first ? [first.name] : []);
      })
      .catch(() => {
        setRuns([]);
        setSelectedRuns([]);
      });
  }, []);

  useEffect(() => {
    if (runs === null) return;
    setRows(null);
    setExpanded(new Set());
    setOpenJudging(new Set());
    if (!selectedRuns.length) {
      setRows([]);
      return;
    }
    api.findings(selectedRuns).then(setRows).catch(() => setRows([]));
  }, [runs, selectedRuns]);

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
    }
  };

  const renderCell = (column: ColumnState, finding: Finding, key: string) => {
    switch (column.id) {
      case "time": {
        const time = finding.ts || finding.run_time || "";
        return <td key={column.id} className="mono muted clip" title={time}>{time || "unknown"}</td>;
      }
      case "run":
        return <td key={column.id} className="mono clip" title={finding.run}>{finding.run || "latest"}</td>;
      case "verdict":
        return (
          <td key={column.id}>
            <span className={`badge ${verdictKind(finding.label)}`}>{finding.label}</span>
          </td>
        );
      case "technique":
        return <td key={column.id} className="mono clip" title={finding.technique}>{finding.technique ?? "manual"}</td>;
      case "category":
        return <td key={column.id} className="mono muted clip" title={finding.category}>{finding.category ?? "-"}</td>;
      case "payload":
        return (
          <td key={column.id}>
            <div className="finding-cell-main">
              <span className="mono clip" title={finding.payload}>{snippet(finding.payload, 260)}</span>
              <button
                type="button"
                className="mini-btn"
                onClick={(ev) => { ev.stopPropagation(); copyText(`${key}-payload`, textValue(finding.payload)); }}
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
  };

  if (!runs || !rows) return <div className="empty">Loading...</div>;
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
                {rows.map((finding, index) => {
                  const key = findingKey(finding, index);
                  const isExpanded = expanded.has(key);
                  return (
                    <Fragment key={key}>
                      <tr
                        className={`run-record-row ${isExpanded ? "expanded" : ""}`}
                        onClick={() => toggleRow(key)}
                      >
                        {columns.map((column) => renderCell(column, finding, key))}
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

function FindingExpanded({
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
              <div><b>Source tool</b><span className="mono">{technique.source_tool || "not recorded"}</span></div>
              <div><b>Preset</b><span className="mono">{technique.preset || "none recorded"}</span></div>
              <div><b>Prompt chain</b><span className="mono">{chainText(technique.transforms?.prompt)}</span></div>
              <div><b>System chain</b><span className="mono">{chainText(technique.transforms?.system)}</span></div>
              <div><b>Response chain</b><span className="mono">{chainText(technique.transforms?.response)}</span></div>
              <div><b>Think seed</b><span className="mono">{technique.think_seed || "none recorded"}</span></div>
              <div><b>Max tokens</b><span className="mono">{textValue(technique.max_tokens) || "not recorded"}</span></div>
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

function TextPanel({
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
