import { useEffect, useMemo, useRef, useState } from "react";
import { api, verdictKind, type ComposeResult, type Preset, type Transform, type FireResult } from "../api";
import { appendActivity } from "../activityLog";
import { maybeNotifyVerdict } from "../notify";

type BusyAction = "compose" | "fire" | "firePayload" | null;

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

const CONSOLE_SESSION_STORE = "wallbreaker.consoleSession.v1";

type ConsoleSession = {
  request?: string;
  preset?: string;
  system?: string;
  maxTokens?: number;
  picked?: string[];
  payload?: string;
  draft?: ComposeResult | null;
  res?: FireResult | null;
  err?: string;
};

function loadConsoleSession(): ConsoleSession {
  try {
    const raw = window.sessionStorage.getItem(CONSOLE_SESSION_STORE);
    if (!raw) return {};
    const value = JSON.parse(raw) as ConsoleSession;
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function saveConsoleSession(patch: ConsoleSession): void {
  try {
    const prev = loadConsoleSession();
    window.sessionStorage.setItem(CONSOLE_SESSION_STORE, JSON.stringify({ ...prev, ...patch }));
  } catch {
    /* ignore */
  }
}

function isAbortError(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError"
    || (e instanceof Error && (/abort|cancel/i.test(e.name) || /abort|cancel|请求已取消/i.test(e.message)));
}

export function Console({ hasTarget }: { hasTarget: boolean }) {
  const restored = useMemo(() => loadConsoleSession(), []);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [transforms, setTransforms] = useState<Transform[]>([]);
  const [request, setRequest] = useState(restored.request || "");
  const [preset, setPreset] = useState(restored.preset || "");
  const [system, setSystem] = useState(restored.system || "");
  const [maxTokens, setMaxTokens] = useState(
    typeof restored.maxTokens === "number" && restored.maxTokens > 0 ? restored.maxTokens : 1024,
  );
  const [picked, setPicked] = useState<string[]>(Array.isArray(restored.picked) ? restored.picked : []);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [stopping, setStopping] = useState(false);
  const [draft, setDraft] = useState<ComposeResult | null>(restored.draft ?? null);
  const [payload, setPayload] = useState(restored.payload || "");
  const [res, setRes] = useState<FireResult | null>(restored.res ?? null);
  const [err, setErr] = useState(restored.err || "");
  const [copied, setCopied] = useState<string | null>(null);
  const busyRef = useRef(false);
  const fireAbortRef = useRef<AbortController | null>(null);

  function begin(action: Exclude<BusyAction, null>): boolean {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(action);
    setStopping(false);
    return true;
  }

  function end() {
    busyRef.current = false;
    setBusy(null);
    setStopping(false);
    fireAbortRef.current = null;
  }

  useEffect(() => {
    api.presets().then(setPresets).catch(() => {});
    api.transforms().then(setTransforms).catch(() => {});
  }, []);

  useEffect(() => {
    saveConsoleSession({
      request,
      preset,
      system,
      maxTokens,
      picked,
      payload,
      draft,
      res,
      err,
    });
  }, [request, preset, system, maxTokens, picked, payload, draft, res, err]);

  // If a previous fire is still held by the backend (e.g. after refresh), allow stop.
  useEffect(() => {
    let cancelled = false;
    api.consoleStatus()
      .then((st) => {
        if (cancelled || !st.active) return;
        busyRef.current = true;
        setBusy("fire");
        setStopping(!!st.stopping);
        appendActivity("console", "检测到进行中的控制台发射（可点结束）", "warn");
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  function toggle(name: string) {
    setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : [...p, name]));
  }

  function attackBody() {
    return {
      request,
      preset: preset || undefined,
      system: system || undefined,
      max_tokens: maxTokens,
      transforms: picked.length ? picked : undefined,
    };
  }

  async function copyText(key: string, text: string) {
    if (!text) return;
    let ok = false;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        ok = true;
      } catch {
        ok = false;
      }
    }
    if (!ok) {
      try {
        ok = fallbackCopy(text);
      } catch {
        ok = false;
      }
    }
    if (ok) {
      setCopied(key);
      window.setTimeout(() => setCopied((cur) => (cur === key ? null : cur)), 1400);
    }
  }

  async function compose() {
    if (!begin("compose")) return;
    setErr("");
    setRes(null);
    try {
      const out = await api.compose(attackBody());
      setDraft(out);
      setPayload(out.payload);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      end();
    }
  }

  function onFireResult(out: FireResult, mode: string) {
    setDraft(out);
    setPayload(out.payload);
    setRes(out);
    if (out.cancelled) {
      appendActivity("console", "控制台发射已结束（已取消）", "warn");
      return;
    }
    const technique = out.preset || mode;
    appendActivity(
      "console",
      `fire ${mode} → ${out.verdict || (out.is_error ? "ERROR" : "?")}  ${String(out.response || out.content || "").slice(0, 240)}`,
      out.verdict?.toUpperCase() === "COMPLIED"
        ? "ok"
        : out.verdict?.toUpperCase() === "PARTIAL"
          ? "warn"
          : out.is_error
            ? "error"
            : "info",
      { verdict: out.verdict, technique },
    );
    maybeNotifyVerdict(out.verdict, {
      technique,
      source: "console",
      detail: String(out.response || out.content || "").slice(0, 160),
    });
  }

  async function fireWith(body: Record<string, unknown>, mode: string) {
    if (!begin(mode === "raw-payload" ? "firePayload" : "fire")) return;
    setErr("");
    setRes(null);
    appendActivity("console", mode === "raw-payload" ? "发射原始载荷…" : "发射编排载荷…", "tool");
    const ac = new AbortController();
    fireAbortRef.current = ac;
    try {
      const out = await api.fire(body, ac.signal);
      onFireResult(out, mode);
    } catch (e) {
      if (isAbortError(e) || stopping) {
        setErr("已结束当前发射。");
        appendActivity("console", "控制台发射已结束", "warn");
      } else {
        setErr((e as Error).message);
        appendActivity("console", `fire failed: ${(e as Error).message}`, "error");
      }
    } finally {
      end();
    }
  }

  async function fire() {
    await fireWith(attackBody(), "compose+fire");
  }

  async function firePayload() {
    await fireWith(
      {
        ...attackBody(),
        payload,
        request: draft?.request || request,
        preset: draft?.preset || preset || undefined,
        transforms: draft?.transforms?.length ? draft.transforms : (picked.length ? picked : undefined),
        system: system || undefined,
        max_tokens: maxTokens,
      },
      "raw-payload",
    );
  }

  async function stopFire() {
    if (!busy || (busy !== "fire" && busy !== "firePayload")) return;
    setStopping(true);
    appendActivity("console", "正在结束控制台发射…", "warn");
    try {
      await api.stopConsole();
    } catch (e) {
      // Backend may already be idle; still abort the browser request.
      appendActivity("console", `stop: ${(e as Error).message}`, "info");
    }
    try {
      fireAbortRef.current?.abort();
    } catch {
      /* ignore */
    }
  }

  const payloadChanged = !!draft && payload !== draft.payload;
  const firing = busy === "fire" || busy === "firePayload";
  const canBuild = !busy && !!request.trim();
  const canFire = !busy && hasTarget && !!request.trim();
  const canFirePayload = !busy && hasTarget && !!payload.trim();
  const responseText = res?.response || res?.content || "";

  return (
    <div className="console-grid">
      <div className="card">
        <h3>编排攻击</h3>
        {!hasTarget && <div className="err">config.toml 中未配置 [target]，发射已禁用。</div>}
        <p className="muted" style={{ marginTop: 0, fontSize: 12 }}>
          与「智能体」独立运行：一方忙碌不会锁死另一方。控制台发射中可随时结束。
        </p>
        <label className="fld">请求内容</label>
        <textarea rows={5} value={request} placeholder="要测试的有害请求…" onChange={(e) => setRequest(e.target.value)} />
        <label className="fld">预设（包装请求）</label>
        <select value={preset} onChange={(e) => setPreset(e.target.value)}>
          <option value="">无（原始发送）</option>
          {presets.map((p) => <option key={p.name} value={p.name}>{p.name} - {p.description.slice(0, 60)}</option>)}
        </select>
        <label className="fld">编码变换（已选 {picked.length}）</label>
        <div className="chips">
          {transforms.map((t) => (
            <span key={t.name} className={`chip ${picked.includes(t.name) ? "on" : ""}`} title={t.description} onClick={() => toggle(t.name)}>
              {t.name}
            </span>
          ))}
        </div>
        <label className="fld">系统提示（可选）</label>
        <textarea rows={2} value={system} placeholder="可选的目标系统提示…" onChange={(e) => setSystem(e.target.value)} />
        <label className="fld">最大 tokens</label>
        <input
          type="number"
          min={1}
          step={1}
          value={maxTokens}
          onChange={(e) => setMaxTokens(Math.max(1, Number.parseInt(e.target.value || "0", 10) || 1))}
        />
        <div className="console-actions">
          <button type="button" className="mini-btn console-build" disabled={!canBuild} onClick={compose}>
            {busy === "compose" ? "构建中…" : "构建载荷"}
          </button>
          <button type="button" className="fire" disabled={!canFire} onClick={() => void fire()}>
            {busy === "fire" ? (stopping ? "正在结束…" : "发射中…") : "向目标发射"}
          </button>
          <button
            type="button"
            className="mini-btn"
            disabled={!firing || stopping}
            onClick={() => void stopFire()}
            title="取消当前控制台发射（不影响智能体）"
          >
            {stopping ? "正在结束…" : "结束发射"}
          </button>
        </div>
        {err && <div className="err console-err">{err}</div>}
      </div>

      <div className="console-side">
        <div className="card">
          <div className="console-card-head">
            <h3>载荷</h3>
            <div className="run-actions">
              {payloadChanged && <span className="badge neutral">已编辑</span>}
              <button type="button" className="mini-btn" disabled={!payload} onClick={() => copyText("payload", payload)}>
                {copied === "payload" ? "已复制" : "复制载荷"}
              </button>
              <button type="button" className="mini-btn" disabled={!canFirePayload} onClick={() => void firePayload()}>
                {busy === "firePayload" ? (stopping ? "正在结束…" : "发射中…") : "发射当前载荷"}
              </button>
              {busy === "firePayload" && (
                <button type="button" className="mini-btn" disabled={stopping} onClick={() => void stopFire()}>
                  {stopping ? "正在结束…" : "结束"}
                </button>
              )}
            </div>
          </div>
          {!payload && <div className="empty">尚未构建载荷。</div>}
          {payload && (
            <textarea
              className="payload-editor"
              rows={12}
              value={payload}
              onChange={(e) => setPayload(e.target.value)}
              spellCheck={false}
            />
          )}
          {draft?.prompt && draft.prompt !== payload && (
            <div className="source-prompt">
              <div className="run-text-head">
                <b>源提示</b>
                <button type="button" className="mini-btn" onClick={() => copyText("source-prompt", draft.prompt)}>
                  {copied === "source-prompt" ? "已复制" : "复制"}
                </button>
              </div>
              <pre>{draft.prompt}</pre>
            </div>
          )}
        </div>

        <div className="card">
          <div className="console-card-head">
            <h3>
              响应{res?.verdict ? <span className={`badge ${verdictKind(res.verdict)}`} style={{ marginLeft: 10 }}>{res.verdict}</span> : null}
              {res?.cancelled ? <span className="badge neutral" style={{ marginLeft: 8 }}>已取消</span> : null}
            </h3>
            <div className="run-actions">
              {res?.run_log && <span className="mono muted">已保存: {res.run_log}</span>}
              <button type="button" className="mini-btn" disabled={!responseText} onClick={() => copyText("response", responseText)}>
                {copied === "response" ? "已复制" : "复制响应"}
              </button>
            </div>
          </div>
          {!res && !err && <div className="empty">暂无响应。</div>}
          {res && <pre className={`resp ${res.is_error ? "is-error" : ""}`}>{responseText}</pre>}
        </div>
      </div>
    </div>
  );
}
