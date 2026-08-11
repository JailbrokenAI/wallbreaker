import { useEffect, useState } from "react";
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

type Tab = "agent" | "overview" | "console" | "findings" | "runs" | "arsenal" | "profiles" | "settings";

const NAV: { id: Tab; label: string; short: string }[] = [
  { id: "agent", label: "Agent", short: "AG" },
  { id: "overview", label: "Overview", short: "OV" },
  { id: "console", label: "Attack console", short: "AC" },
  { id: "findings", label: "Findings", short: "FN" },
  { id: "runs", label: "Run logs", short: "RL" },
  { id: "arsenal", label: "Arsenal", short: "AR" },
  { id: "profiles", label: "Profiles", short: "PR" },
  { id: "settings", label: "Settings", short: "ST" },
];

function tabFromHash(): Tab {
  const h = window.location.hash.replace("#", "");
  return (NAV.some((n) => n.id === h) ? h : "agent") as Tab;
}

export function App() {
  const [tab, setTabState] = useState<Tab>(tabFromHash());
  const [railCollapsed, setRailCollapsed] = useState(
    () => window.innerWidth < 700 || window.localStorage.getItem("wallbreaker.railCollapsed") === "true",
  );
  const setTab = (t: Tab) => { setTabState(t); window.location.hash = t; };
  const [cfg, setCfg] = useState<ConfigInfo | null>(null);
  const [ov, setOv] = useState<OverviewT | null>(null);
  const [roles, setRoles] = useState<RoleAssignments | null>(null);

  const refresh = () => {
    api.config().then(setCfg).catch(() => setCfg(null));
    api.overview().then(setOv).catch(() => setOv(null));
    api.roles().then(setRoles).catch(() => setRoles(null));
  };
  useEffect(refresh, [tab]);

  const asr = ov?.scorecard?.asr;
  const asrStr = typeof asr === "number" ? `${Math.round(asr * 100)}%` : "—";
  const toggleRail = () => {
    setRailCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem("wallbreaker.railCollapsed", String(next));
      return next;
    });
  };

  return (
    <div className={`app ${railCollapsed ? "rail-collapsed" : ""}`}>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <nav className="rail" aria-label="Primary navigation">
        <div className="brand">
          <span className="mark">◆</span>
          <span className="word">{railCollapsed ? "WB" : <>WALL<b>BREAKER</b></>}</span>
          <button
            type="button"
            className="rail-toggle"
            onClick={toggleRail}
            title={railCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={railCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!railCollapsed}
          >
            {railCollapsed ? "›" : "‹"}
          </button>
        </div>
        {NAV.map((n) => (
          <button
            type="button"
            key={n.id}
            className={`nav-item ${tab === n.id ? "active" : ""}`}
            onClick={() => setTab(n.id)}
            title={railCollapsed ? n.label : undefined}
            aria-current={tab === n.id ? "page" : undefined}
          >
            <span className="dot" />
            <span className="nav-label">{railCollapsed ? n.short : n.label}</span>
          </button>
        ))}
        <div className="spacer" />
        <div className="foot">
          break the wall ·<br />
          not the rules of engagement
        </div>
      </nav>

      <div className="main">
        <div className="topbar">
          <h1 className="title">{NAV.find((n) => n.id === tab)?.label}</h1>
          <div className="meta">
            {roles && (["attacker", "target", "judge"] as const).map((role) => <RoleChooser
              key={role} role={role} value={roles[role]} onSaved={refresh}
            />)}
            <span className="pill">ASR {asrStr}</span>
          </div>
        </div>
        <main id="main-content" className="content">
          {tab === "agent" && <Agent hasTarget={!!cfg?.has_target} />}
          {tab === "overview" && <Overview ov={ov} />}
          {tab === "console" && <Console hasTarget={!!cfg?.has_target} />}
          {tab === "findings" && <Findings />}
          {tab === "runs" && <Runs />}
          {tab === "arsenal" && <Arsenal />}
          {tab === "settings" && <Settings onSaved={refresh} />}
          {tab === "profiles" && <Profiles onSaved={refresh} />}
        </main>
      </div>
    </div>
  );
}
