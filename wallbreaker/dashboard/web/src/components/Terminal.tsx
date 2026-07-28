import { useEffect, useMemo, useRef, useState } from "react";
import {
  appendActivity,
  clearActivity,
  getActivity,
  subscribeActivity,
  type ActivityLevel,
  type ActivityLine,
  type ActivitySource,
} from "../activityLog";
import { desktop, isDesktop } from "../desktop";
import { zh } from "../i18n/zh";

type StreamFilter = "all" | ActivitySource;

const LEVEL_CLASS: Record<ActivityLevel, string> = {
  debug: "lvl-debug",
  info: "lvl-info",
  tool: "lvl-tool",
  ok: "lvl-ok",
  warn: "lvl-warn",
  error: "lvl-error",
  system: "lvl-system",
};

const SOURCE_LABEL: Record<StreamFilter, string> = {
  all: zh.terminal.sources.all,
  agent: zh.terminal.sources.agent,
  backend: zh.terminal.sources.backend,
  console: zh.terminal.sources.console,
  system: zh.terminal.sources.system,
  desktop: zh.terminal.sources.desktop,
};

function fmtTime(ts: number): string {
  const d = new Date(ts);
  return (
    d.toLocaleTimeString(undefined, { hour12: false }) +
    "." +
    String(d.getMilliseconds()).padStart(3, "0")
  );
}

export function Terminal() {
  const [lines, setLines] = useState<ActivityLine[]>(() => getActivity(800));
  const [filter, setFilter] = useState<StreamFilter>("all");
  const [query, setQuery] = useState("");
  const [follow, setFollow] = useState(true);
  const [wrap, setWrap] = useState(true);
  const scroller = useRef<HTMLDivElement | null>(null);
  const desktopBound = useRef(false);

  useEffect(() => {
    return subscribeActivity((line) => {
      setLines((prev) => {
        const next = [...prev, line];
        return next.length > 2000 ? next.slice(-2000) : next;
      });
    });
  }, []);

  useEffect(() => {
    if (!isDesktop() || desktopBound.current) return;
    desktopBound.current = true;
    const api = desktop();
    if (!api) return;

    appendActivity("system", zh.activity.desktopAttached, "system");
    api
      .getLog()
      .then((log) => {
        for (const row of log.split("\n")) {
          if (row.trim()) appendActivity("backend", row, classifyBackend(row));
        }
      })
      .catch(() => undefined);

    const off = api.onLog((row) => {
      if (row.trim()) appendActivity("backend", row, classifyBackend(row));
    });
    return off;
  }, []);

  useEffect(() => {
    if (!follow || !scroller.current) return;
    scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [lines, follow, filter, query]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return lines.filter((l) => {
      if (filter !== "all" && l.source !== filter) return false;
      if (q && !l.text.toLowerCase().includes(q) && l.source !== q) return false;
      return true;
    });
  }, [lines, filter, query]);

  const copyAll = async () => {
    const text = visible.map((l) => `${fmtTime(l.ts)} [${l.source}] ${l.text}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      appendActivity("system", `已复制 ${visible.length} 行`, "system");
    } catch {
      appendActivity("system", "剪贴板写入失败", "error");
    }
  };

  return (
    <div className="terminal-page">
      <div className="terminal-toolbar">
        <div className="terminal-filters">
          {(["all", "agent", "backend", "console", "system", "desktop"] as StreamFilter[]).map((f) => (
            <button
              key={f}
              type="button"
              className={`term-chip ${filter === f ? "active" : ""}`}
              onClick={() => setFilter(f)}
            >
              {SOURCE_LABEL[f]}
            </button>
          ))}
        </div>
        <input
          className="term-search"
          placeholder={zh.terminal.filterText}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
        />
        <div className="terminal-actions">
          <label className="term-check">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
            {zh.common.follow}
          </label>
          <label className="term-check">
            <input type="checkbox" checked={wrap} onChange={(e) => setWrap(e.target.checked)} />
            {zh.common.wrap}
          </label>
          <button type="button" className="ghost-command" onClick={copyAll}>
            {zh.common.copy}
          </button>
          <button
            type="button"
            className="ghost-command"
            onClick={async () => {
              const text = visible
                .map((l) => `${fmtTime(l.ts)} [${l.source}] ${l.text}`)
                .join("\n");
              const api = desktop();
              if (api?.exportLog) {
                const path = await api.exportLog(text);
                if (path) appendActivity("desktop", `已导出 → ${path}`, "ok");
              } else {
                await navigator.clipboard.writeText(text);
                appendActivity("system", "已复制（无桌面导出）", "system");
              }
            }}
          >
            {zh.common.export}
          </button>
          <button
            type="button"
            className="ghost-command"
            onClick={() => {
              clearActivity();
              setLines(getActivity(800));
            }}
          >
            {zh.common.clear}
          </button>
        </div>
      </div>

      <div
        className={`terminal-body ${wrap ? "wrap" : "nowrap"}`}
        ref={scroller}
        onScroll={() => {
          const el = scroller.current;
          if (!el) return;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          if (!atBottom && follow) setFollow(false);
        }}
      >
        {visible.length === 0 ? (
          <div className="terminal-empty">
            <div>{zh.terminal.empty}</div>
            <div className="muted">
              {zh.terminal.emptyHint}
              {isDesktop() ? ` ${zh.terminal.emptyHintDesktop}` : ""}
            </div>
          </div>
        ) : (
          visible.map((l) => (
            <div key={l.id} className={`term-line ${LEVEL_CLASS[l.level]}`}>
              <span className="term-ts">{fmtTime(l.ts)}</span>
              <span className={`term-src src-${l.source}`}>{SOURCE_LABEL[l.source] || l.source}</span>
              <span className="term-text">{l.text}</span>
            </div>
          ))
        )}
      </div>

      <div className="terminal-foot">
        <span>
          {visible.length} {zh.terminal.lines}
        </span>
        <span className="muted">
          {isDesktop() ? zh.terminal.desktopStream : zh.terminal.browserStream}
        </span>
        {!follow && (
          <button type="button" className="term-chip active" onClick={() => setFollow(true)}>
            {zh.terminal.jumpLive}
          </button>
        )}
      </div>
    </div>
  );
}

function classifyBackend(row: string): ActivityLevel {
  if (/error|traceback|failed|exception/i.test(row)) return "error";
  if (/warn/i.test(row)) return "warn";
  if (/ready|started|Uvicorn running/i.test(row)) return "ok";
  if (/\[desktop\]/i.test(row)) return "system";
  return "info";
}
