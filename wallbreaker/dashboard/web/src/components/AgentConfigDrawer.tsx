import { useEffect, useState } from "react";
import type { AgentConfig } from "../api";

export const DEFAULT_AGENT_CONFIG: AgentConfig = {
  max_rounds: 8,
  max_tokens: 8192,
};

function clampNumber(value: number, fallback: number, lo: number, hi: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.max(lo, Math.min(hi, Math.trunc(value)));
}

export function normalizeAgentConfig(value?: Partial<AgentConfig> | null): AgentConfig {
  return {
    max_rounds: clampNumber(Number(value?.max_rounds), DEFAULT_AGENT_CONFIG.max_rounds, 1, 50),
    max_tokens: clampNumber(Number(value?.max_tokens), DEFAULT_AGENT_CONFIG.max_tokens, 1, 32000),
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
  });

  useEffect(() => {
    setDraft({ max_rounds: String(value.max_rounds), max_tokens: String(value.max_tokens) });
  }, [value.max_rounds, value.max_tokens]);

  const setField = (key: keyof AgentConfig, raw: string) => {
    setDraft((current) => ({ ...current, [key]: raw }));
    if (!/^\d+$/.test(raw)) return;
    onChange({ ...value, [key]: Number.parseInt(raw, 10) });
  };

  const restoreEmpty = (key: keyof AgentConfig) => {
    if (!draft[key]) setDraft((current) => ({ ...current, [key]: String(value[key]) }));
  };

  return (
    <details className="config-drawer">
      <summary>
        <span>Agent configuration</span>
        <span className="mono muted">{value.max_rounds} rounds | {value.max_tokens} tokens</span>
      </summary>
      <div className="config-drawer-body">
        <label className="fld">Max rounds</label>
        <input
          type="number"
          min={1}
          max={50}
          step={1}
          value={draft.max_rounds}
          onChange={(event) => setField("max_rounds", event.target.value)}
          onBlur={() => restoreEmpty("max_rounds")}
          disabled={disabled}
        />
        <label className="fld">Max tokens per response</label>
        <input
          type="number"
          max={32000}
          step={1}
          value={draft.max_tokens}
          onChange={(event) => setField("max_tokens", event.target.value)}
          onBlur={() => restoreEmpty("max_tokens")}
          disabled={disabled}
        />
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
