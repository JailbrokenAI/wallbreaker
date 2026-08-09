import { useEffect, useState } from "react";
import { api, type DaedalusOptions as DaedalusOptionsT } from "../api";

const DEFAULTS: DaedalusOptionsT = {
  codename: "Daedalus",
  topology: "dual",
  doctrine_enabled: true,
  doctrine_file: "wallbreaker/doctrine/liberation_agent.md",
  memory_scope: "global",
  memory_root: "library/liberation",
  cyber_gate_enabled: true,
  memory_require_validate: true,
  memory_embed_provider: "offline",
  memory_embed_model: "",
  memory_embed_base_url: "",
  memory_embed_api_key_env: "",
  memory_embed_profile: "",
  memory_embed_dimensions: 0,
  memory_embed_has_key: false,
  memory_embed_mode: "offline-hash",
};

export function DaedalusOptions() {
  const [value, setValue] = useState<DaedalusOptionsT>(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    api
      .settings()
      .then((settings) => setValue({ ...DEFAULTS, ...(settings.daedalus || {}) }))
      .catch((error) => setStatus((error as Error).message));
  }, []);

  const save = async () => {
    setBusy(true);
    setStatus("");
    try {
      const settings = await api.saveSettings({ daedalus: value });
      setValue({ ...DEFAULTS, ...(settings.daedalus || {}) });
      setStatus("saved");
    } catch (error) {
      setStatus((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="settings-drawer" open>
      <summary>
        <span>
          <b>Daedalus harness</b>
          <small>Topology, liberation doctrine, cyber gate, and memory policy</small>
        </span>
      </summary>
      <div className="drawer-body">
        <div className="form-grid">
          <label>
            Codename
            <input
              value={value.codename}
              onChange={(event) => setValue({ ...value, codename: event.target.value })}
            />
          </label>
          <label>
            Topology
            <select
              value={value.topology}
              onChange={(event) =>
                setValue({
                  ...value,
                  topology: event.target.value as DaedalusOptionsT["topology"],
                })
              }
            >
              <option value="dual">Dual — brain and target may differ</option>
              <option value="single">Single — target mirrors brain</option>
            </select>
          </label>
          <label className="wide">
            Doctrine file
            <input
              value={value.doctrine_file}
              onChange={(event) => setValue({ ...value, doctrine_file: event.target.value })}
            />
          </label>
          <label className="wide">
            Liberation memory root
            <input
              value={value.memory_root}
              onChange={(event) => setValue({ ...value, memory_root: event.target.value })}
            />
          </label>
          <label className="toggle-field">
            <input
              type="checkbox"
              checked={value.doctrine_enabled}
              onChange={(event) =>
                setValue({ ...value, doctrine_enabled: event.target.checked })
              }
            />
            <span>Inject liberation doctrine into brain system prompt</span>
          </label>
          <label className="toggle-field">
            <input
              type="checkbox"
              checked={value.cyber_gate_enabled}
              onChange={(event) =>
                setValue({ ...value, cyber_gate_enabled: event.target.checked })
              }
            />
            <span>Cyber gate — prose refusal → MODE LIBERATE rescue</span>
          </label>
          <label className="toggle-field">
            <input
              type="checkbox"
              checked={value.memory_require_validate}
              onChange={(event) =>
                setValue({ ...value, memory_require_validate: event.target.checked })
              }
            />
            <span>Require validate rate before writing Liberation Memory</span>
          </label>
          <label>
            Memory embed provider
            <select
              value={value.memory_embed_provider || "offline"}
              onChange={(event) =>
                setValue({ ...value, memory_embed_provider: event.target.value })
              }
            >
              <option value="offline">Offline hash (default, no network)</option>
              <option value="openai">OpenAI embeddings</option>
              <option value="openrouter">OpenRouter embeddings</option>
              <option value="custom">Custom OpenAI-compatible</option>
            </select>
          </label>
          <label>
            Embed model
            <input
              value={value.memory_embed_model || ""}
              placeholder="text-embedding-3-small"
              onChange={(event) =>
                setValue({ ...value, memory_embed_model: event.target.value })
              }
            />
          </label>
          <label className="wide">
            Embed base URL
            <input
              value={value.memory_embed_base_url || ""}
              placeholder="https://api.openai.com/v1"
              onChange={(event) =>
                setValue({ ...value, memory_embed_base_url: event.target.value })
              }
            />
          </label>
          <label>
            Embed API key env
            <input
              value={value.memory_embed_api_key_env || ""}
              placeholder="OPENAI_API_KEY"
              onChange={(event) =>
                setValue({ ...value, memory_embed_api_key_env: event.target.value })
              }
            />
          </label>
          <label>
            Embed profile (borrow key/url)
            <input
              value={value.memory_embed_profile || ""}
              placeholder="optional profile name"
              onChange={(event) =>
                setValue({ ...value, memory_embed_profile: event.target.value })
              }
            />
          </label>
          <label>
            Embed dimensions (0 = provider default)
            <input
              type="number"
              min={0}
              value={value.memory_embed_dimensions ?? 0}
              onChange={(event) =>
                setValue({
                  ...value,
                  memory_embed_dimensions: Number(event.target.value) || 0,
                })
              }
            />
          </label>
        </div>
        <div className="mono muted">
          Memory scope is global ({value.memory_scope}). Topology=single rewrites target on
          save. Embed mode: {value.memory_embed_mode || "offline-hash"}
          {value.memory_embed_has_key ? " (key present)" : ""}. Env overrides:
          WALLBREAKER_TOPOLOGY, WALLBREAKER_DOCTRINE, WALLBREAKER_CYBER_GATE,
          WALLBREAKER_MEMORY_REQUIRE_VALIDATE, WALLBREAKER_MEMORY_EMBED_PROVIDER,
          WALLBREAKER_MEMORY_EMBED=0.
        </div>
        <div className="editor-actions">
          <button type="button" className="primary-command" disabled={busy} onClick={() => void save()}>
            {busy ? "Saving..." : "Save Daedalus"}
          </button>
          {status && <span className="mono muted">{status}</span>}
        </div>
      </div>
    </details>
  );
}
