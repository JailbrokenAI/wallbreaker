import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type ModelPoolItem, type RoleAssignments, type RoleChoice } from "../api";
import { zh } from "../i18n/zh";
import { Dialog } from "../primitives/Dialog";

const ROLE_LABEL: Record<string, string> = {
  attacker: zh.roles.attacker,
  target: zh.roles.target,
  judge: zh.roles.judge,
};

export function RoleChooser({
  role,
  value,
  onSaved,
}: {
  role: keyof Pick<RoleAssignments, "attacker" | "target" | "judge">;
  value: RoleChoice;
  onSaved: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [pool, setPool] = useState<ModelPoolItem[]>([]);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const close = useCallback(() => {
    setOpen(false);
    queueMicrotask(() => trigger.current?.focus());
  }, []);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setError("");
    const request = api.modelPool?.();
    if (!request) {
      setPool([]);
      setLoading(false);
      return;
    }
    request
      .then((res) => setPool(res.items || []))
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return pool;
    return pool.filter(
      (item) =>
        item.model.toLowerCase().includes(q) ||
        item.provider.toLowerCase().includes(q) ||
        item.label.toLowerCase().includes(q),
    );
  }, [pool, query]);

  const grouped = useMemo(() => {
    const map = new Map<string, ModelPoolItem[]>();
    for (const item of filtered) {
      const list = map.get(item.provider) || [];
      list.push(item);
      map.set(item.provider, list);
    }
    return [...map.entries()];
  }, [filtered]);

  const apply = async (item: ModelPoolItem) => {
    setBusy(true);
    setError("");
    try {
      await api.saveRole(role, { provider: item.provider, model: item.model });
      setOpen(false);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const currentId = value.provider && value.model ? `${value.provider}::${value.model}` : "";

  return (
    <div className="role-chooser" ref={root}>
      <button ref={trigger} type="button" className="role-chip" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={`${role} model chooser`}>
        <span>{ROLE_LABEL[role] || role}</span>
        <b>{value.model || "未设置"}</b>
        <small>{value.provider ? value.provider : "从模型池选择"}</small>
      </button>
      <Dialog open={open} title={`Configure ${ROLE_LABEL[role] || role}`} onClose={close}>
        <div className="role-menu role-menu-pool">
          <div className="role-menu-title">从模型池选择</div>
          <input
            className="role-menu-search"
            placeholder="搜索模型或提供商…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            autoFocus
          />
          {loading && <div className="muted" style={{ fontSize: 12 }}>加载模型池…</div>}
          {!loading && !pool.length && (
            <div className="empty compact" style={{ padding: 16 }}>
              模型池为空。请到「设置 → 模型池」添加 URL + Key 并探测入库。
            </div>
          )}
          <div className="role-pool-list">
            {grouped.map(([provider, items]) => (
              <div key={provider} className="role-pool-group">
                <div className="role-pool-provider">{provider}</div>
                {items.map((item) => {
                  const active = item.id === currentId;
                  return (
                    <button
                      type="button"
                      key={item.id}
                      className={`role-pool-item ${active ? "active" : ""}`}
                      disabled={busy}
                      onClick={() => void apply(item)}
                      title={item.base_url}
                    >
                      <span className="mono">{item.model}</span>
                      {item.is_default && <span className="pill">默认</span>}
                      {active && <span className="pill desktop-pill">当前</span>}
                    </button>
                  );
                })}
              </div>
            ))}
            {!loading && pool.length > 0 && !filtered.length && (
              <div className="empty compact">无匹配项</div>
            )}
          </div>
          {error && <div className="err">{error}</div>}
        </div>
      </Dialog>
    </div>
  );
}
