import { useEffect, useState } from "react";
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
  saveLabel = "保存为默认",
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

  return (
    <details className="config-drawer">
      <summary>
        <span>智能体配置</span>
        <span className="mono muted">
          {value.max_rounds} 轮 | {value.max_tokens} tokens | 并发 {value.concurrency} | {value.request_delay_ms} ms
        </span>
      </summary>
      <div className="config-drawer-body">
        <label className="fld">最大轮数</label>
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
        <label className="fld">每次响应最大 tokens</label>
        <input
          type="number"
          min={1}
          max={32000}
          step={1}
          value={draft.max_tokens}
          onChange={(event) => setField("max_tokens", event.target.value)}
          onBlur={() => restoreEmpty("max_tokens")}
          disabled={disabled}
        />
        <label className="fld">并发推理请求数</label>
        <input
          type="number"
          min={1}
          max={32}
          step={1}
          value={draft.concurrency}
          onChange={(event) => setField("concurrency", event.target.value)}
          onBlur={() => restoreEmpty("concurrency")}
          disabled={disabled}
        />
        <label className="fld">请求启动间隔（毫秒）</label>
        <input
          type="number"
          min={0}
          max={60000}
          step={50}
          value={draft.request_delay_ms}
          onChange={(event) => setField("request_delay_ms", event.target.value)}
          onBlur={() => restoreEmpty("request_delay_ms")}
          disabled={disabled}
        />
        <div className="mono muted">
          作用于攻击端、目标、评判及其工具触发的推理调用。更高并发更快；间隔用于拉开请求起点，降低限流突发。
        </div>
        {(onSave || status) && (
          <div className="config-drawer-actions">
            {onSave && (
              <button type="button" className="mini-btn" disabled={disabled || saving} onClick={onSave}>
                {saving ? "保存中…" : saveLabel}
              </button>
            )}
            {status && <span className="mono muted">{status}</span>}
          </div>
        )}
      </div>
    </details>
  );
}
