import { useEffect, useMemo, useState } from "react";
import { api, type Preset, type Transform, type Tool } from "../api";

type Kind = "presets" | "transforms" | "tools";
type ArsenalRow = {
  key: string;
  kind: Kind;
  name: string;
  desc: string;
  tag: string;
  badges: string[];
  detail: string;
};

export function Arsenal() {
  const [kind, setKind] = useState<Kind>("presets");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [transforms, setTransforms] = useState<Transform[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [q, setQ] = useState("");
  const [selectedKey, setSelectedKey] = useState("");
  const [copied, setCopied] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    api.presets()
      .then((items) => {
        setPresets(Array.isArray(items) ? items : []);
        setLoadError("");
      })
      .catch((error) => setLoadError(error instanceof Error ? error.message : "Could not load presets."));
    api.transforms().then((items) => setTransforms(Array.isArray(items) ? items : [])).catch(() => {});
    api.tools().then((items) => setTools(Array.isArray(items) ? items : [])).catch(() => {});
  }, []);

  const rows = useMemo<ArsenalRow[]>(() => {
    const source: ArsenalRow[] = kind === "presets" ? presets.map((preset) => {
        const template = typeof preset.template === "string" ? preset.template : "";
        return {
          key: `presets:${preset.name}`, kind, name: preset.name, desc: preset.description,
          tag: "prompt template", badges: ["prompt template", `${template.length.toLocaleString()} chars`],
          detail: template || "This dashboard process did not return the preset prompt. Restart it to load the current preset API.",
        };
      })
      : kind === "transforms"
        ? transforms.map((transform) => ({
            key: `transforms:${transform.name}`, kind, name: transform.name, desc: transform.description,
            tag: transform.lossy ? "lossy" : transform.reversible ? "reversible" : "one-way",
            badges: [transform.lossy ? "lossy" : "lossless", transform.reversible ? "reversible" : "one-way"],
            detail: transform.description,
          }))
        : tools.map((tool) => ({
            key: `tools:${tool.name}`, kind, name: tool.name, desc: tool.description,
            tag: tool.control ? "run control" : "agent technique",
            badges: [tool.control ? "run control" : "agent technique"],
            detail: JSON.stringify(tool.parameters || {}, null, 2),
          }));
    const needle = q.trim().toLowerCase();
    return source.filter((row) => !needle
      || row.name.toLowerCase().includes(needle)
      || row.desc.toLowerCase().includes(needle)
      || row.tag.includes(needle));
  }, [kind, q, presets, transforms, tools]);

  const selected = rows.find((row) => row.key === selectedKey) || rows[0];
  const counts = { presets: presets.length, transforms: transforms.length, tools: tools.length };

  async function copyDetail() {
    if (!selected) return;
    await navigator.clipboard.writeText(selected.detail);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1300);
  }

  return (
    <div className="arsenal-layout">
      <section className="card arsenal-list-card">
        <div className="section-title arsenal-kind-tabs">
          {(["presets", "transforms", "tools"] as Kind[]).map((item) => (
            <button
              type="button"
              key={item}
              className={`chip ${kind === item ? "on" : ""}`}
              onClick={() => { setKind(item); setSelectedKey(""); }}
            >
              {item === "tools" ? "agent techniques" : item} ({counts[item]})
            </button>
          ))}
          <div className="rule" />
        </div>
        {loadError && <div className="err">Could not load presets: {loadError}</div>}
        <input className="search" type="search" placeholder={`Search ${kind}…`} value={q} onChange={(event) => setQ(event.target.value)} />
        <div className="arsenal-table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Type</th><th>Description</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.key}
                  className={`arsenal-row ${selected?.key === row.key ? "selected" : ""}`}
                  tabIndex={0}
                  role="button"
                  aria-label={`View ${row.name}`}
                  onClick={() => setSelectedKey(row.key)}
                  onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedKey(row.key); } }}
                >
                  <td className="mono accent">{row.name}</td>
                  <td className="mono muted">{row.tag}</td>
                  <td className="muted">{row.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!rows.length && <div className="empty">No matches.</div>}
      </section>

      <aside className="card arsenal-detail" aria-live="polite">
        {selected ? <>
          <div className="arsenal-detail-head">
            <div><h2>{selected.name}</h2><div className="arsenal-meta">{selected.badges.map((badge) => <span className="badge neutral" key={badge}>{badge}</span>)}</div></div>
            <button type="button" className="mini-btn" onClick={() => void copyDetail()}>{copied ? "Copied" : "Copy"}</button>
          </div>
          <p className="description">{selected.desc}</p>
          <h3>{selected.kind === "presets" ? "Prompt template" : selected.kind === "tools" ? "Input schema" : "Properties"}</h3>
          {selected.kind === "transforms"
            ? <div className="mono muted">{selected.detail}</div>
            : <pre>{selected.detail}</pre>}
        </> : <div className="empty">Select an arsenal item to inspect it.</div>}
      </aside>
    </div>
  );
}
