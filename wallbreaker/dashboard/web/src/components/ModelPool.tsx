import { useEffect, useMemo, useState } from "react";
import { api, type ModelPoolItem, type ProviderRecord } from "../api";
import { invalidateModelCatalog, invalidateProviders, loadProviders } from "../dataCache";

const PRESETS: { id: string; label: string; protocol: string; base_url: string; auth_style: string; api_key_env: string }[] = [
  { id: "openai", label: "OpenAI 官方", protocol: "openai", base_url: "https://api.openai.com/v1", auth_style: "bearer", api_key_env: "OPENAI_API_KEY" },
  { id: "deepseek", label: "DeepSeek", protocol: "openai", base_url: "https://api.deepseek.com", auth_style: "bearer", api_key_env: "DEEPSEEK_API_KEY" },
  { id: "openrouter", label: "OpenRouter", protocol: "openai", base_url: "https://openrouter.ai/api/v1", auth_style: "bearer", api_key_env: "OPENROUTER_API_KEY" },
  { id: "cpa", label: "本地 CPA", protocol: "openai", base_url: "http://127.0.0.1:8317/v1", auth_style: "bearer", api_key_env: "CPA_API_KEY" },
  { id: "anthropic", label: "Anthropic", protocol: "anthropic", base_url: "https://api.anthropic.com", auth_style: "x-api-key", api_key_env: "ANTHROPIC_API_KEY" },
  { id: "custom", label: "自定义", protocol: "openai", base_url: "", auth_style: "bearer", api_key_env: "" },
];

function slugify(input: string): string {
  return input
    .trim()
    .toLowerCase()
    .replace(/https?:\/\//g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32) || "provider";
}

export function ModelPool({ onChanged }: { onChanged?: () => void }) {
  const [providers, setProviders] = useState<ProviderRecord[]>([]);
  const [pool, setPool] = useState<ModelPoolItem[]>([]);
  const [presetId, setPresetId] = useState("custom");
  const [name, setName] = useState("");
  const [protocol, setProtocol] = useState("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiKeyEnv, setApiKeyEnv] = useState("");
  const [authStyle, setAuthStyle] = useState("bearer");
  const [discovered, setDiscovered] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [probeUrl, setProbeUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  const reload = async () => {
    const [plist, poolRes] = await Promise.all([loadProviders(true), api.modelPool()]);
    setProviders(plist);
    setPool(poolRes.items || []);
  };

  useEffect(() => {
    void reload().catch((err) => setError((err as Error).message));
  }, []);

  const applyPreset = (id: string) => {
    setPresetId(id);
    const preset = PRESETS.find((item) => item.id === id);
    if (!preset) return;
    if (id !== "custom") {
      setName((prev) => prev || preset.id);
      setProtocol(preset.protocol);
      setBaseUrl(preset.base_url);
      setAuthStyle(preset.auth_style);
      setApiKeyEnv(preset.api_key_env);
    }
    setDiscovered([]);
    setSelected(new Set());
    setProbeUrl("");
    setStatus("");
    setError("");
  };

  const filteredDiscovered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return discovered;
    return discovered.filter((m) => m.toLowerCase().includes(q));
  }, [discovered, filter]);

  const probe = async () => {
    const url = baseUrl.trim();
    if (!url) {
      setError("请填写 Base URL");
      return;
    }
    setBusy(true);
    setError("");
    setStatus("正在探测模型列表…");
    try {
      const result = await api.probeProvider({
        name: name.trim() || undefined,
        protocol,
        base_url: url,
        api_key: apiKey || undefined,
        auth_style: authStyle,
      });
      if (!result.ok) throw new Error(result.error || "探测失败");
      setDiscovered(result.models || []);
      setSelected(new Set(result.models || []));
      setProbeUrl(result.url || "");
      setStatus(`探测成功 · 发现 ${result.models.length} 个模型`);
    } catch (err) {
      setDiscovered([]);
      setSelected(new Set());
      setError((err as Error).message);
      setStatus("");
    } finally {
      setBusy(false);
    }
  };

  const toggle = (model: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(model)) next.delete(model);
      else next.add(model);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(filteredDiscovered));
  const selectNone = () => setSelected(new Set());

  const saveToPool = async () => {
    const providerName = (name.trim() || slugify(baseUrl)).replace(/\s+/g, "-");
    if (!baseUrl.trim()) {
      setError("请填写 Base URL");
      return;
    }
    if (!selected.size) {
      setError("请至少勾选一个模型加入池子");
      return;
    }
    const models = [...selected];
    const defaultModel = models[0];
    const envName = (apiKeyEnv.trim() || `${providerName.replace(/[^a-zA-Z0-9]+/g, "_").toUpperCase()}_API_KEY`);
    setBusy(true);
    setError("");
    setStatus("正在写入模型池…");
    try {
      await api.saveProvider(providerName, {
        name: providerName,
        protocol,
        base_url: baseUrl.trim(),
        model: defaultModel,
        api_key_env: envName,
        api_key: apiKey || undefined,
        auth_style: authStyle,
        enabled: true,
        modality: "text",
        timeout: 120,
      });
      await api.addModelsBulk(providerName, models);
      invalidateProviders();
      invalidateModelCatalog(providerName);
      setStatus(`已加入模型池：${providerName} · ${models.length} 个模型`);
      setApiKey("");
      await reload();
      onChanged?.();
    } catch (err) {
      setError((err as Error).message);
      setStatus("");
    } finally {
      setBusy(false);
    }
  };

  const removeProvider = async (providerName: string) => {
    if (!window.confirm(`从模型池移除提供商「${providerName}」？`)) return;
    setBusy(true);
    try {
      await api.deleteProvider(providerName);
      invalidateProviders();
      invalidateModelCatalog(providerName);
      await reload();
      onChanged?.();
      setStatus(`已移除 ${providerName}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const byProvider = useMemo(() => {
    const map = new Map<string, ModelPoolItem[]>();
    for (const item of pool) {
      const list = map.get(item.provider) || [];
      list.push(item);
      map.set(item.provider, list);
    }
    return [...map.entries()];
  }, [pool]);

  return (
    <div className="model-pool">
      <div className="model-pool-head">
        <div>
          <h3>模型池</h3>
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            填写 URL + API Key → 探测模型 → 勾选入库。顶栏攻击端 / 目标 / 评判直接从池中切换。
          </div>
        </div>
        <span className="pill">{pool.length} 个可选模型</span>
      </div>

      <div className="model-pool-presets">
        {PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className={`chip ${presetId === preset.id ? "on" : ""}`}
            onClick={() => applyPreset(preset.id)}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="model-pool-form">
        <label>
          名称
          <input
            value={name}
            placeholder="例如 deepseek / cpa / my-proxy"
            onChange={(e) => setName(e.target.value)}
            spellCheck={false}
          />
        </label>
        <label>
          协议
          <select
            value={protocol}
            onChange={(e) => {
              setProtocol(e.target.value);
              setAuthStyle(e.target.value === "anthropic" ? "x-api-key" : "bearer");
            }}
          >
            <option value="openai">OpenAI 兼容</option>
            <option value="anthropic">Anthropic 兼容</option>
          </select>
        </label>
        <label className="span-2">
          Base URL
          <input
            value={baseUrl}
            placeholder="https://api.example.com/v1"
            onChange={(e) => setBaseUrl(e.target.value)}
            spellCheck={false}
          />
        </label>
        <label>
          API Key
          <input
            type="password"
            value={apiKey}
            placeholder={name && providers.some((p) => p.name === name && p.has_api_key) ? "已存储；填写则覆盖" : "sk-..."}
            onChange={(e) => setApiKey(e.target.value)}
            spellCheck={false}
          />
        </label>
        <label>
          密钥环境变量
          <input
            value={apiKeyEnv}
            placeholder="自动生成，如 DEEPSEEK_API_KEY"
            onChange={(e) => setApiKeyEnv(e.target.value)}
            spellCheck={false}
          />
        </label>
      </div>

      <div className="model-pool-actions">
        <button type="button" className="primary-command" disabled={busy} onClick={() => void probe()}>
          {busy ? "处理中…" : "探测模型"}
        </button>
        <button
          type="button"
          className="ghost-command"
          disabled={busy || !selected.size}
          onClick={() => void saveToPool()}
        >
          将勾选模型加入池子
        </button>
        {probeUrl && <span className="mono muted">GET {probeUrl}</span>}
      </div>

      {status && <div className="desktop-msg">{status}</div>}
      {error && <div className="err" style={{ marginTop: 10 }}>{error}</div>}

      {!!discovered.length && (
        <div className="model-pool-discover">
          <div className="model-pool-discover-toolbar">
            <input
              className="term-search"
              placeholder="筛选探测到的模型…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
            <button type="button" className="mini-btn" onClick={selectAll}>全选</button>
            <button type="button" className="mini-btn" onClick={selectNone}>清空</button>
            <span className="mono muted">已选 {selected.size}/{discovered.length}</span>
          </div>
          <div className="model-pool-check-grid">
            {filteredDiscovered.map((model) => (
              <label key={model} className={`model-pool-check ${selected.has(model) ? "on" : ""}`}>
                <input type="checkbox" checked={selected.has(model)} onChange={() => toggle(model)} />
                <span className="mono">{model}</span>
              </label>
            ))}
            {!filteredDiscovered.length && <div className="empty compact">无匹配模型</div>}
          </div>
        </div>
      )}

      <div className="model-pool-current">
        <h3>池中模型</h3>
        {!byProvider.length && (
          <div className="empty compact">模型池为空。上方探测并勾选后加入。</div>
        )}
        {byProvider.map(([providerName, items]) => {
          const meta = providers.find((p) => p.name === providerName);
          return (
            <div key={providerName} className="model-pool-group">
              <div className="model-pool-group-head">
                <div>
                  <b>{providerName}</b>
                  <small className="mono muted">
                    {" "}{meta?.protocol || items[0]?.protocol} · {meta?.base_url || items[0]?.base_url || "—"}
                  </small>
                </div>
                <button
                  type="button"
                  className="mini-btn"
                  disabled={busy}
                  onClick={() => void removeProvider(providerName)}
                >
                  移除
                </button>
              </div>
              <div className="model-pool-tags">
                {items.map((item) => (
                  <span key={item.id} className={`chip ${item.is_default ? "on" : ""}`} title={item.id}>
                    {item.model}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
