import { useEffect, useMemo, useRef, useState } from "react";
import { desktop, isDesktop } from "../desktop";
import { appendActivity } from "../activityLog";
import { zh } from "../i18n/zh";

export type PaletteCommand = {
  id: string;
  label: string;
  hint?: string;
  group: string;
  keywords?: string;
  run: () => void | Promise<void>;
};

export function CommandPalette({
  open,
  onClose,
  commands,
}: {
  open: boolean;
  onClose: () => void;
  commands: PaletteCommand[];
}) {
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter((c) => {
      const hay = `${c.label} ${c.hint || ""} ${c.group} ${c.keywords || ""}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [commands, q]);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setIdx(0);
    const t = window.setTimeout(() => inputRef.current?.focus(), 20);
    return () => window.clearTimeout(t);
  }, [open]);

  useEffect(() => {
    setIdx(0);
  }, [q]);

  if (!open) return null;

  const run = async (cmd: PaletteCommand) => {
    onClose();
    try {
      await cmd.run();
      appendActivity("system", `命令：${cmd.label}`, "system");
    } catch (err) {
      appendActivity("system", `命令失败：${(err as Error).message}`, "error");
    }
  };

  return (
    <div className="palette-backdrop" onMouseDown={onClose} role="presentation">
      <div
        className="palette"
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={zh.nav.commandPalette}
      >
        <input
          ref={inputRef}
          className="palette-input"
          placeholder={zh.palette.placeholder}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              onClose();
            } else if (e.key === "ArrowDown") {
              e.preventDefault();
              setIdx((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setIdx((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              const cmd = filtered[idx];
              if (cmd) void run(cmd);
            }
          }}
        />
        <div className="palette-list">
          {filtered.length === 0 ? (
            <div className="palette-empty">{zh.palette.noMatches}</div>
          ) : (
            filtered.map((cmd, i) => (
              <button
                type="button"
                key={cmd.id}
                className={`palette-item ${i === idx ? "active" : ""}`}
                onMouseEnter={() => setIdx(i)}
                onClick={() => void run(cmd)}
              >
                <span className="palette-group">{cmd.group}</span>
                <span className="palette-label">{cmd.label}</span>
                {cmd.hint && <span className="palette-hint">{cmd.hint}</span>}
              </button>
            ))
          )}
        </div>
        <div className="palette-foot">
          <span>{zh.palette.navHint}</span>
          <span>{zh.palette.runHint}</span>
          <span>{zh.palette.escHint}</span>
          {isDesktop() && <span>桌面端</span>}
        </div>
      </div>
    </div>
  );
}

export function useDesktopPaletteHooks(handlers: {
  openPalette: () => void;
  runDiagnostics: () => void;
  showShortcuts: () => void;
}): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        handlers.openPalette();
      }
      if (ctrl && e.key === "/") {
        e.preventDefault();
        handlers.showShortcuts();
      }
      if (ctrl && e.shiftKey && e.key.toLowerCase() === "d" && isDesktop()) {
        e.preventDefault();
        handlers.runDiagnostics();
      }
    };
    window.addEventListener("keydown", onKey);

    const api = desktop();
    const offs: Array<() => void> = [];
    if (api?.onCommandPalette) offs.push(api.onCommandPalette(handlers.openPalette));
    if (api?.onRunDiagnostics) offs.push(api.onRunDiagnostics(handlers.runDiagnostics));
    if (api?.onShowShortcuts) offs.push(api.onShowShortcuts(handlers.showShortcuts));

    return () => {
      window.removeEventListener("keydown", onKey);
      offs.forEach((off) => off());
    };
  }, [handlers]);
}
