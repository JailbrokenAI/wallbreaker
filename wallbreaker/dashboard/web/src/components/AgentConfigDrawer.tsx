import { useEffect, useId, useState } from "react";
import type { AgentConfig } from "../api";

export const DEFAULT_AGENT_CONFIG: AgentConfig = {
  max_rounds: 8,
  max_tokens: 8192,
  concurrency: 3,
  request_delay_ms: 250,
};

function clampNumber(value: number, fallback: number, lo: number, hi: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.max(lo, Math.min(hi, Math.trunc(value)));
}

export function normalizeAgentConfig(value?: Partial<AgentConfig> | null): AgentConfig {
  return {
    max_rounds: clampNumber(Number(value?.max_rounds), DEFAULT_AGENT_CONFIG.max_rounds, 1, 50),
    max_tokens: clampNumber(Number(value?.max_tokens), DEFAULT_AGENT_CONFIG.max_tokens, 1, 32000),
    concurrency: clampNumber(Number(value?.concurrency), DEFAULT_AGENT_CONFIG.concurrency, 1, 32),
    request_delay_ms: clampNumber(Number(value?.request_delay_ms), DEFAULT_AGENT_CONFIG.request_delay_ms, 0, 60000),
  };
}

export function AgentConfigDrawer({
  value,
  onChange,
  disabled = false,
  onSave,
  saveLabel = "Save defaults",
  saving = false,
  status = "",
}: {
  value: AgentConfig;
  onChange: (value: AgentConfig) => void;
  disabled?: boolean;
  onSave?: () => void;
  saveLabel?: string;
  saving?: boolean;
  status?: string;
}) {
  const [draft, setDraft] = useState({
    max_rounds: String(value.max_rounds),
    max_tokens: String(value.max_tokens),
    concurrency: String(value.concurrency),
    request_delay_ms: String(value.request_delay_ms),
  });

  useEffect(() => {
    setDraft({
      max_rounds: String(value.max_rounds),
      max_tokens: String(value.max_tokens),
      concurrency: String(value.concurrency),
      request_delay_ms: String(value.request_delay_ms),
    });
  }, [value.max_rounds, value.max_tokens, value.concurrency, value.request_delay_ms]);

  const setField = (key: keyof AgentConfig, raw: string) => {
    setDraft((current) => ({ ...current, [key]: raw }));
    if (!/^\d+$/.test(raw)) return;
    onChange({ ...value, [key]: Number.parseInt(raw, 10) });
  };

  const restoreEmpty = (key: keyof AgentConfig) => {
    if (!draft[key]) setDraft((current) => ({ ...current, [key]: String(value[key]) }));
  };

  const ids = useId();
  // A11Y-10/A11Y-11: one focusable number input per field, its <label> associated
  // by htmlFor/id and its min/max range exposed to assistive tech via a
  // aria-describedby helper line (announced with the input, not just visual).
  const numberField = (
    key: keyof AgentConfig,
    label: string,
    min: number,
    max: number,
    step: number,
  ) => {
    const fieldId = `${ids}-${key}`;
    const helpId = `${ids}-${key}-help`;
    return (
      <>
        <label className="fld" htmlFor={fieldId}>{label}</label>
        <input
          id={fieldId}
          type="number"
          min={min}
          max={max}
          step={step}
          aria-describedby={helpId}
          value={draft[key]}
          onChange={(event) => setField(key, event.target.value)}
          onBlur={() => restoreEmpty(key)}
          disabled={disabled}
        />
        <div id={helpId} className="mono muted">Allowed range: {min}–{max}.</div>
      </>
    );
  };

  return (
    <details className="config-drawer">
      <summary>
        <span>Agent configuration</span>
        <span className="mono muted">
          {value.max_rounds} rounds | {value.max_tokens} tokens | {value.concurrency} concurrent | {value.request_delay_ms} ms
        </span>
      </summary>
      <div className="config-drawer-body">
        {numberField("max_rounds", "Max rounds", 1, 50, 1)}
        {numberField("max_tokens", "Max tokens per response", 1, 32000, 1)}
        {numberField("concurrency", "Concurrent inference requests", 1, 32, 1)}
        {numberField("request_delay_ms", "Delay between request starts (ms)", 0, 60000, 50)}
        <div className="mono muted">
          Applied across attacker, target, judge, and their tool-driven inference calls. Higher concurrency is faster; the delay spaces request starts to reduce rate-limit bursts.
        </div>
        {(onSave || status) && (
          <div className="config-drawer-actions">
            {onSave && (
              <button type="button" className="mini-btn" disabled={disabled || saving} onClick={onSave}>
                {saving ? "Saving..." : saveLabel}
              </button>
            )}
            {status && <span className="mono muted">{status}</span>}
          </div>
        )}
      </div>
    </details>
  );
}
