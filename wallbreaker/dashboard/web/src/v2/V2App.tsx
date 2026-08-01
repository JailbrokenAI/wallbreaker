import { useCallback, useEffect, useMemo, useState } from "react";
import { api as legacyApi, type RoleAssignments } from "../api";
import { RoleChooser } from "../components/RoleChooser";
import { v2Api } from "./api";
import { CommandPalette, ROUTES } from "./CommandPalette";
import { formatTime, StatusBadge } from "./components";
import { LiveView } from "./LiveView";
import {
  ArsenalView,
  ComposeView,
  FindingsView,
  ModelsView,
  ReportsView,
  RunsView,
  SettingsView,
  WorkflowsView,
} from "./Views";
import type { Capability, ExecutionSummary, V2Route } from "./types";

function routeFromLocation(): V2Route {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const candidate = hash.startsWith("v2/") ? hash.slice(3).split("/")[0] : hash.split("/")[0];
  return ROUTES.some((item) => item.id === candidate) ? candidate as V2Route : "live";
}

function isActive(execution: ExecutionSummary) {
  return ["queued", "running", "pausing", "paused"].includes(execution.status);
}

export function V2App() {
  const [route, setRouteState] = useState<V2Route>(routeFromLocation);
  const [railOpen, setRailOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [capabilities, setCapabilities] = useState<Capability[]>([]);
  const [capabilitySource, setCapabilitySource] = useState<"v2" | "legacy">("legacy");
  const [executions, setExecutions] = useState<ExecutionSummary[]>([]);
  const [selectedExecutionId, setSelectedExecutionId] = useState("");
  const [initialCapability, setInitialCapability] = useState("");
  const [roles, setRoles] = useState<RoleAssignments | null>(null);

  const refreshExecutions = useCallback(() => {
    v2Api.executions().then((result) => {
      setExecutions(result.data);
      setSelectedExecutionId((current) => {
        if (current && result.data.some((item) => item.id === current)) return current;
        return result.data.find(isActive)?.id || result.data[0]?.id || "";
      });
    }).catch(() => setExecutions([]));
  }, []);

  const refreshRoles = useCallback(() => {
    legacyApi.roles().then(setRoles).catch(() => setRoles(null));
  }, []);

  useEffect(() => {
    v2Api.capabilities().then((result) => { setCapabilities(result.data); setCapabilitySource(result.source); }).catch(() => setCapabilities([]));
    refreshExecutions();
    refreshRoles();
    const timer = window.setInterval(refreshExecutions, 5000);
    return () => window.clearInterval(timer);
  }, [refreshExecutions, refreshRoles]);

  useEffect(() => {
    const update = () => setRouteState(routeFromLocation());
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);

  useEffect(() => {
    const open = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", open);
    return () => window.removeEventListener("keydown", open);
  }, []);

  const navigate = useCallback((next: V2Route) => {
    setRouteState(next);
    setRailOpen(false);
    setPaletteOpen(false);
    window.location.hash = `v2/${next}`;
  }, []);

  const chooseCapability = useCallback((capability: Capability) => {
    setInitialCapability(capability.id);
    navigate("workflows");
  }, [navigate]);

  const selectedExecution = executions.find((item) => item.id === selectedExecutionId) || null;
  const activeExecutions = executions.filter(isActive);
  const recentExecutions = executions.filter((item) => !isActive(item)).slice(0, 5);
  const routeInfo = ROUTES.find((item) => item.id === route) || ROUTES[0];
  const view = useMemo(() => {
    if (route === "live") return <LiveView execution={selectedExecution} onRefresh={refreshExecutions} />;
    if (route === "compose") return <ComposeView />;
    if (route === "workflows") return <WorkflowsView capabilities={capabilities} initialCapability={initialCapability} onConsumed={() => setInitialCapability("")} />;
    if (route === "arsenal") return <ArsenalView />;
    if (route === "findings") return <FindingsView />;
    if (route === "runs") return <RunsView />;
    if (route === "reports") return <ReportsView />;
    if (route === "models") return <ModelsView />;
    return <SettingsView />;
  }, [route, selectedExecution, refreshExecutions, capabilities, initialCapability]);

  return (
    <div className="v2-root">
      <a className="v2-skip" href="#v2-main">Skip to main content</a>
      <aside className={`v2-rail ${railOpen ? "open" : ""}`} aria-label="V2 navigation">
        <div className="v2-brand"><span aria-hidden="true">◆</span><strong>WALL<b>BREAKER</b></strong><small>V2</small><button type="button" aria-label="Close navigation" onClick={() => setRailOpen(false)}>Close</button></div>
        <nav>{ROUTES.map((item) => <button type="button" key={item.id} className={route === item.id ? "active" : ""} aria-current={route === item.id ? "page" : undefined} onClick={() => navigate(item.id)}><span aria-hidden="true">●</span>{item.label}</button>)}</nav>
        <section className="v2-rail-section" aria-label="Active executions">
          <header><span>Active run</span><span>{activeExecutions.length}</span></header>
          {!activeExecutions.length && <p>No active execution</p>}
          {activeExecutions.map((execution) => <button type="button" key={execution.id} className={selectedExecutionId === execution.id ? "selected" : ""} onClick={() => { setSelectedExecutionId(execution.id); navigate("live"); }}><strong>{execution.title || execution.id}</strong><StatusBadge status={execution.status} /><small>{execution.current_round ? `Round ${execution.current_round}${execution.max_rounds ? ` of ${execution.max_rounds}` : ""}` : "Waiting for round data"}</small></button>)}
        </section>
        <section className="v2-rail-section v2-run-queue" aria-label="Run queue and history">
          <header><span>Run queue</span><span>{executions.length}</span></header>
          {[...activeExecutions, ...recentExecutions].slice(0, 7).map((execution) => <button type="button" key={`queue-${execution.id}`} className={selectedExecutionId === execution.id ? "selected" : ""} onClick={() => { setSelectedExecutionId(execution.id); navigate("live"); }}><span aria-hidden="true">●</span><strong>{execution.title || execution.run_id || execution.id}</strong><small>{execution.status} / {formatTime(execution.created_at || execution.started_at)}</small></button>)}
        </section>
        <div className="v2-rail-foot"><span className="v2-status v2-status-running"><span aria-hidden="true">●</span>Local operator</span><small>Capability catalog: {capabilitySource}</small></div>
      </aside>
      <div className="v2-shell">
        <header className="v2-mobile-header"><button type="button" onClick={() => setRailOpen(true)} aria-label="Open navigation">Menu</button><div className="v2-brand"><span aria-hidden="true">◆</span><strong>WALL<b>BREAKER</b></strong></div><button type="button" onClick={() => setPaletteOpen(true)}>Commands</button></header>
        <header className="v2-page-header v2-operator-bar">
          <div className="v2-route-heading"><span>Wallbreaker V2</span><h1>{routeInfo.label}</h1><p>{routeInfo.description}</p></div>
          <div className="v2-operator-controls">
            {roles && (["attacker", "target", "judge"] as const).map((role) => <RoleChooser
              key={role}
              role={role}
              value={roles[role]}
              onSaved={() => { refreshRoles(); refreshExecutions(); }}
            />)}
            {selectedExecution && <button
              type="button"
              className="v2-active-run"
              onClick={() => navigate("live")}
              title="Open the active run in Live"
            ><StatusBadge status={selectedExecution.status} /><strong>{selectedExecution.title || selectedExecution.id}</strong></button>}
            <button type="button" className="v2-command-button" onClick={() => setPaletteOpen(true)}>Commands <kbd>Ctrl K</kbd></button>
          </div>
        </header>
        <main id="v2-main" className={route === "live" ? "v2-main v2-main-live" : "v2-main"}>{view}</main>
      </div>
      <CommandPalette open={paletteOpen} capabilities={capabilities} onClose={() => setPaletteOpen(false)} onNavigate={navigate} onCapability={chooseCapability} />
    </div>
  );
}

export default V2App;
