import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ConfigInfo, type Overview as OverviewT, type RoleAssignments } from "./api";
import { Agent } from "./components/Agent";
import { Overview } from "./components/Overview";
import { Console } from "./components/Console";
import { Findings } from "./components/Findings";
import { Runs } from "./components/Runs";
import { Arsenal } from "./components/Arsenal";
import { Settings } from "./components/Settings";
import { RoleChooser } from "./components/RoleChooser";
import { Profiles } from "./components/Profiles";
import { Terminal } from "./components/Terminal";
import { DesktopStatus } from "./components/DesktopStatus";
import { ErrorBoundary } from "./components/ErrorBoundary";
import {
  CommandPalette,
  useDesktopPaletteHooks,
  type PaletteCommand,
} from "./components/CommandPalette";
import { ShortcutsHelp } from "./components/ShortcutsHelp";
import { DiagnosticsModal } from "./components/DiagnosticsModal";
import { Icons } from "./components/Icons";
import { desktop, isDesktop, type DiagnosticsReport } from "./desktop";
import { appendActivity, getActivity } from "./activityLog";
import { zh } from "./i18n/zh";

type Tab =
  | "agent"
  | "overview"
  | "console"
  | "terminal"
  | "findings"
  | "runs"
  | "arsenal"
  | "profiles"
  | "settings";

const NAV: {
  id: Tab;
  label: string;
  short: string;
  icon: keyof typeof Icons;
  group?: string;
}[] = [
  { id: "agent", label: zh.nav.agent, short: zh.navShort.agent, icon: "agent", group: "工作区" },
  { id: "overview", label: zh.nav.overview, short: zh.navShort.overview, icon: "overview" },
  { id: "console", label: zh.nav.console, short: zh.navShort.console, icon: "console" },
  { id: "terminal", label: zh.nav.terminal, short: zh.navShort.terminal, icon: "terminal" },
  { id: "findings", label: zh.nav.findings, short: zh.navShort.findings, icon: "findings", group: "证据" },
  { id: "runs", label: zh.nav.runs, short: zh.navShort.runs, icon: "runs" },
  { id: "arsenal", label: zh.nav.arsenal, short: zh.navShort.arsenal, icon: "arsenal", group: "系统" },
  { id: "profiles", label: zh.nav.profiles, short: zh.navShort.profiles, icon: "profiles" },
  { id: "settings", label: zh.nav.settings, short: zh.navShort.settings, icon: "settings" },
];

function tabFromHash(): Tab {
  const h = window.location.hash.replace("#", "");
  return (NAV.some((n) => n.id === h) ? h : "agent") as Tab;
}

export function App() {
  const [tab, setTabState] = useState<Tab>(tabFromHash());
  /** Keep visited tabs mounted so Agent/Console state survives navigation. */
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set([tabFromHash()]));
  const [railCollapsed, setRailCollapsed] = useState(
    () => window.innerWidth < 700 || window.localStorage.getItem("wallbreaker.railCollapsed") === "true",
  );
  const setTab = useCallback((t: Tab) => {
    setTabState(t);
    setVisited((prev) => {
      if (prev.has(t)) return prev;
      const next = new Set(prev);
      next.add(t);
      return next;
    });
    window.location.hash = t;
  }, []);
  const [cfg, setCfg] = useState<ConfigInfo | null>(null);
  const [ov, setOv] = useState<OverviewT | null>(null);
  const [roles, setRoles] = useState<RoleAssignments | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [diagOpen, setDiagOpen] = useState(false);
  const [diagBusy, setDiagBusy] = useState(false);
  const [diagReport, setDiagReport] = useState<DiagnosticsReport | null>(null);
  const [theme, setTheme] = useState<"light" | "dark">(
    () => (document.documentElement.dataset.theme === "dark" ? "dark" : "light"),
  );
  const toggleTheme = useCallback(() => {
    setTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      window.localStorage.setItem("wallbreaker.theme", next);
      return next;
    });
  }, []);

  const refresh = useCallback(() => {
    api.config().then(setCfg).catch(() => setCfg(null));
    api.overview().then(setOv).catch(() => setOv(null));
    api.roles().then(setRoles).catch(() => setRoles(null));
  }, []);

  useEffect(refresh, [tab, refresh]);

  useEffect(() => {
    appendActivity("system", zh.activity.ready, "system");
    const onHash = () => {
      const next = tabFromHash();
      setTabState(next);
      setVisited((prev) => {
        if (prev.has(next)) return prev;
        const copy = new Set(prev);
        copy.add(next);
        return copy;
      });
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const runDiagnostics = useCallback(async () => {
    const apiDesktop = desktop();
    if (!apiDesktop?.diagnostics) {
      appendActivity("system", zh.diagnostics.needDesktop, "warn");
      setDiagOpen(true);
      setDiagReport({
        ok: false,
        generatedAt: new Date().toISOString(),
        summary: zh.diagnostics.needDesktop,
        checks: [
          {
            id: "desktop",
            label: "桌面外壳",
            ok: false,
            detail: zh.diagnostics.needDesktopDetail,
          },
        ],
      });
      return;
    }
    setDiagOpen(true);
    setDiagBusy(true);
    try {
      const report = await apiDesktop.diagnostics();
      setDiagReport(report);
      appendActivity("desktop", `诊断：${report.summary}`, report.ok ? "ok" : "warn");
    } catch (err) {
      appendActivity("desktop", `诊断失败：${(err as Error).message}`, "error");
    } finally {
      setDiagBusy(false);
    }
  }, []);

  const handlers = useMemo(
    () => ({
      openPalette: () => setPaletteOpen(true),
      runDiagnostics,
      showShortcuts: () => setShortcutsOpen(true),
    }),
    [runDiagnostics],
  );
  useDesktopPaletteHooks(handlers);

  const commands = useMemo<PaletteCommand[]>(() => {
    const navCmds: PaletteCommand[] = NAV.map((n, i) => ({
      id: `nav-${n.id}`,
      label: `${zh.palette.goTo} ${n.label}`,
      group: zh.palette.navigate,
      hint: `Ctrl+${i + 1}`,
      keywords: `${n.id} ${n.label}`,
      run: () => setTab(n.id),
    }));

    const sys: PaletteCommand[] = [
      {
        id: "refresh",
        label: zh.palette.refresh,
        group: zh.palette.app,
        run: () => refresh(),
      },
      {
        id: "shortcuts",
        label: zh.palette.shortcuts,
        group: zh.palette.app,
        hint: "Ctrl+/",
        run: () => setShortcutsOpen(true),
      },
      {
        id: "toggle-rail",
        label: railCollapsed ? zh.palette.expandSidebar : zh.palette.collapseSidebar,
        group: zh.palette.app,
        run: () => {
          setRailCollapsed((c) => {
            const next = !c;
            window.localStorage.setItem("wallbreaker.railCollapsed", String(next));
            return next;
          });
        },
      },
    ];

    if (isDesktop()) {
      const d = desktop()!;
      sys.push(
        {
          id: "diag",
          label: zh.palette.diagnostics,
          group: zh.palette.desktopGroup,
          hint: "Ctrl+Shift+D",
          run: () => runDiagnostics(),
        },
        {
          id: "restart-backend",
          label: zh.palette.restartBackend,
          group: zh.palette.desktopGroup,
          hint: "Ctrl+Shift+R",
          run: async () => {
            appendActivity("desktop", "正在重启后端…", "system");
            await d.restartBackend();
          },
        },
        {
          id: "open-settings-desktop",
          label: zh.palette.desktopSettings,
          group: zh.palette.desktopGroup,
          hint: "Ctrl+,",
          run: () => {
            setTab("settings");
            window.setTimeout(() => {
              window.dispatchEvent(new CustomEvent("wallbreaker:open-desktop-settings"));
            }, 50);
          },
        },
        {
          id: "open-project",
          label: zh.palette.openProject,
          group: zh.palette.desktopGroup,
          run: async () => {
            const info = await d.getInfo();
            await d.openPath(info.projectRoot);
          },
        },
        {
          id: "open-sessions",
          label: zh.palette.openSessions,
          group: zh.palette.desktopGroup,
          run: async () => {
            const info = await d.getInfo();
            await d.openPath(`${info.projectRoot}/sessions`);
          },
        },
        {
          id: "export-log",
          label: zh.palette.exportLog,
          group: zh.palette.desktopGroup,
          run: async () => {
            const text = getActivity(2000)
              .map((l) => `${new Date(l.ts).toISOString()} [${l.source}] ${l.text}`)
              .join("\n");
            const path = await d.exportLog(text);
            if (path) appendActivity("desktop", `日志已导出 → ${path}`, "ok");
          },
        },
        {
          id: "copy-diag",
          label: zh.palette.copyEnv,
          group: zh.palette.desktopGroup,
          run: async () => {
            const info = await d.getInfo();
            const st = await d.getStatus();
            await d.copyText(JSON.stringify({ info, status: st }, null, 2));
            appendActivity("desktop", "环境信息已复制", "ok");
          },
        },
      );
    }

    return [...navCmds, ...sys];
  }, [railCollapsed, refresh, runDiagnostics, setTab]);

  const asr = ov?.scorecard?.asr;
  const asrStr = typeof asr === "number" ? `${Math.round(asr * 100)}%` : "—";
  const toggleRail = () => {
    setRailCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("wallbreaker.railCollapsed", String(next));
      return next;
    });
  };

  let lastGroup = "";

  const codename = (cfg?.daedalus?.codename || zh.brand || "Daedalus").trim() || "Daedalus";
  const brandParts = (() => {
    const raw = codename;
    const lower = raw.toLowerCase();
    if (lower === "daedalus") return ["DAE", "DALUS"] as const;
    if (lower === "wallbreaker") return ["WALL", "BREAKER"] as const;
    if (raw.length >= 6) {
      const mid = Math.max(3, Math.floor((raw.length * 2) / 5));
      return [raw.slice(0, mid).toUpperCase(), raw.slice(mid).toUpperCase()] as const;
    }
    return ["", raw.toUpperCase()] as const;
  })();
  const brandShort = (codename[0] || "D").toUpperCase();

  return (
    <div className={`app ${railCollapsed ? "rail-collapsed" : ""}`}>
      <a href="#main-content" className="skip-link">跳到主要内容</a>
      <nav className="rail" aria-label="主导航">
        <div className="brand">
          <span className="mark">◆</span>
          {!railCollapsed ? (
            <span className="brand-meta">
              <span className="word">
                {brandParts[0]}<b>{brandParts[1]}</b>
              </span>
              <span className="brand-sub">{zh.brandSub}</span>
            </span>
          ) : (
            <span className="word">{brandShort}</span>
          )}
          <button
            type="button"
            className="rail-toggle"
            onClick={toggleRail}
            title={railCollapsed ? zh.palette.expandSidebar : zh.palette.collapseSidebar}
            aria-label={railCollapsed ? zh.palette.expandSidebar : zh.palette.collapseSidebar}
            aria-expanded={!railCollapsed}
          >
            <Icons.panelLeft size={15} />
          </button>
        </div>

        {NAV.map((n) => {
          const showGroup = !!n.group && n.group !== lastGroup && !railCollapsed;
          if (n.group) lastGroup = n.group;
          const Icon = Icons[n.icon];
          return (
            <div key={n.id}>
              {showGroup && <div className="nav-section">{n.group}</div>}
              <button
                type="button"
                className={`nav-item ${tab === n.id ? "active" : ""}`}
                onClick={() => setTab(n.id)}
                title={railCollapsed ? n.label : undefined}
                aria-current={tab === n.id ? "page" : undefined}
              >
                <span className="nav-ico">
                  <Icon size={16} />
                </span>
                <span className="nav-label">{railCollapsed ? n.short : n.label}</span>
              </button>
            </div>
          );
        })}

        <div className="spacer" />
        <button
          type="button"
          className="nav-item palette-trigger"
          onClick={() => setPaletteOpen(true)}
          title={`${zh.nav.commandPalette} (Ctrl+K)`}
        >
          <span className="nav-ico">
            <Icons.search size={16} />
          </span>
          <span className="nav-label">{railCollapsed ? "⌘K" : zh.nav.commandPalette}</span>
          {!railCollapsed && <span className="nav-kbd">Ctrl K</span>}
        </button>
        <div className="foot">{zh.foot}</div>
      </nav>

      <div className="main">
        <div className="topbar">
          <h1 className="title">
            {NAV.find((n) => n.id === tab)?.label}
            {tab === "agent" && <span className="title-sub">自主攻击循环</span>}
            {tab === "console" && <span className="title-sub">单次发射</span>}
            {tab === "terminal" && <span className="title-sub">实时活动流</span>}
          </h1>
          <div className="meta">
            {roles &&
              (["attacker", "target", "judge"] as const).map((role) => (
                <RoleChooser key={role} role={role} value={roles[role]} onSaved={refresh} />
              ))}
            <span
              className="pill mode-pill mode-code"
              title="Daedalus default mode (CODE). LIBERATE/REPLAY appear on agent runs."
            >
              CODE
            </span>
            {cfg?.daedalus?.topology === "single" && (
              <span className="pill" title="Daedalus topology">
                single
              </span>
            )}
            {cfg?.daedalus?.cyber_gate_enabled === false && (
              <span className="pill" title="Cyber gate disabled">
                gate off
              </span>
            )}
            <span className="pill" title="Attack Success Rate">
              {zh.topbar.asr} {asrStr}
            </span>
            {isDesktop() && (
              <span className="pill desktop-pill" title="运行于 Daedalus 桌面端">
                {zh.topbar.desktop}
              </span>
            )}
            <DesktopStatus />
            <button
              type="button"
              className="theme-toggle"
              onClick={toggleTheme}
              title={theme === "dark" ? "切换到浅色模式" : "切换到深色模式"}
              aria-label="切换主题"
            >
              {theme === "dark" ? "☀" : "☾"}
            </button>
          </div>
        </div>
        <main id="main-content" className={`content ${tab === "terminal" ? "content-flush" : ""}`}>
          {visited.has("agent") && (
            <div className="tab-keep" hidden={tab !== "agent"}>
              <ErrorBoundary label={zh.nav.agent}>
                <Agent hasTarget={!!cfg?.has_target} />
              </ErrorBoundary>
            </div>
          )}
          {visited.has("overview") && (
            <div className="tab-keep" hidden={tab !== "overview"}>
              <ErrorBoundary label={zh.nav.overview}>
                <Overview ov={ov} />
              </ErrorBoundary>
            </div>
          )}
          {visited.has("console") && (
            <div className="tab-keep" hidden={tab !== "console"}>
              <ErrorBoundary label={zh.nav.console}>
                <Console hasTarget={!!cfg?.has_target} />
              </ErrorBoundary>
            </div>
          )}
          {visited.has("terminal") && (
            <div className="tab-keep tab-keep-fill" hidden={tab !== "terminal"}>
              <ErrorBoundary label={zh.nav.terminal}>
                <Terminal />
              </ErrorBoundary>
            </div>
          )}
          {visited.has("findings") && (
            <div className="tab-keep" hidden={tab !== "findings"}>
              <ErrorBoundary label={zh.nav.findings}>
                <Findings />
              </ErrorBoundary>
            </div>
          )}
          {visited.has("runs") && (
            <div className="tab-keep" hidden={tab !== "runs"}>
              <ErrorBoundary label={zh.nav.runs}>
                <Runs />
              </ErrorBoundary>
            </div>
          )}
          {visited.has("arsenal") && (
            <div className="tab-keep" hidden={tab !== "arsenal"}>
              <ErrorBoundary label={zh.nav.arsenal}>
                <Arsenal />
              </ErrorBoundary>
            </div>
          )}
          {visited.has("profiles") && (
            <div className="tab-keep" hidden={tab !== "profiles"}>
              <ErrorBoundary label={zh.nav.profiles}>
                <Profiles onSaved={refresh} />
              </ErrorBoundary>
            </div>
          )}
          {visited.has("settings") && (
            <div className="tab-keep" hidden={tab !== "settings"}>
              <ErrorBoundary label={zh.nav.settings}>
                <Settings onSaved={refresh} />
              </ErrorBoundary>
            </div>
          )}
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} commands={commands} />
      <ShortcutsHelp open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <DiagnosticsModal
        open={diagOpen}
        report={diagReport}
        busy={diagBusy}
        onClose={() => setDiagOpen(false)}
        onRerun={() => void runDiagnostics()}
        onCopy={() => {
          if (!diagReport) return;
          const text = JSON.stringify(diagReport, null, 2);
          const d = desktop();
          if (d?.copyText) void d.copyText(text);
          else void navigator.clipboard.writeText(text);
          appendActivity("system", "诊断报告已复制", "ok");
        }}
      />
    </div>
  );
}
