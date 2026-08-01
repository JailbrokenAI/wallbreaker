export interface ConfigInfo {
  has_target: boolean;
  target: string | null;
  target_modality?: string;
  profile: string | null;
  judge: string | null;
}

export interface Scorecard {
  asr?: number;
  total?: number;
  hits?: number;
  grade?: string;
  by_technique?: Record<string, { hits: number; total: number }>;
  by_category?: Record<string, { hits: number; total: number }>;
  [k: string]: unknown;
}

export interface Overview {
  config: ConfigInfo;
  scorecard: Scorecard;
  findings_count: number;
  runs_count: number;
  latest_run: string | null;
}

export interface Finding {
  id?: string;
  run?: string;
  run_time?: string;
  ts?: string;
  line?: number;
  record_index?: number;
  label: string;
  technique?: string;
  payload?: string;
  reason?: string;
  response?: string;
  category?: string;
  raw?: string;
  models?: RunModels;
  conversation?: FindingTurn[];
  technique_detail?: FindingTechnique;
  judging?: FindingJudging;
  fields?: Record<string, unknown>;
  [k: string]: unknown;
}

export interface FindingTurn {
  role: string;
  content: string;
  source?: string;
}

export interface FindingTechnique {
  technique?: string;
  source_tool?: string;
  preset?: string;
  template?: string;
  instructions?: string;
  think_seed?: string;
  max_tokens?: unknown;
  transforms?: {
    prompt?: string[];
    system?: string[];
    response?: string[];
  };
  raw_args?: Record<string, unknown>;
}

export interface FindingJudging {
  source?: string;
  label?: string;
  reason?: string;
  score?: unknown;
  criteria?: string;
  template?: string;
}

export interface RunSummary {
  name: string;
  time?: string;
  models?: RunModels;
  size: number;
  records: number;
  hits: number;
  findings?: number;
}

export interface RunModels {
  attacker?: string;
  target?: string;
  judge?: string;
  recorded?: boolean;
}

export interface RunDetail {
  name: string;
  total: number;
  records: Record<string, unknown>[];
  raw_records?: string[];
  line_numbers?: number[];
}

export interface Settings {
  profiles: string[];
  profile_details?: Record<string, ProfileDetail>;
  default_profile: string | null;
  attacker_model: string | null;
  target: { model: string; modality: string; base_url: string; protocol: string; provider: string[] } | null;
  target_profile?: string | null;
  judge_model: string | null;
  judge_profile?: string | null;
  agent?: AgentConfig;
  target_options?: TargetOptions;
}

export interface ProfileDetail {
  name: string;
  model: string;
  protocol: string;
  base_url: string;
  modality: string;
}

export interface ModelCatalog {
  profile: string;
  protocol: string;
  models: string[];
  fetched: boolean;
  error: string;
}

export interface ProviderTestResult extends ModelCatalog {
  ok: boolean;
  model: string;
  inference: {
    ok: boolean;
    kind: "completion" | "image_generation";
    latency_ms: number;
    response_preview: string;
  };
}

export interface ProviderRecord extends ProfileDetail {
  enabled: boolean;
  api_key_env: string;
  has_api_key: boolean;
  auth_style: string;
  inference_path: string;
  models_path: string;
  timeout: number;
  reasoning: boolean;
}

export interface RoleChoice {
  provider: string;
  model: string;
  profile: string;
  custom: boolean;
  prompt_source: "none" | "inline" | "file";
  has_system_prompt: boolean;
}

export type RoleAssignments = Record<"attacker" | "target" | "judge", RoleChoice>;

export interface AgentConfig {
  max_rounds: number;
  max_tokens: number;
  concurrency: number;
  request_delay_ms: number;
}

export interface TargetOptions {
  modality: "auto" | "text" | "image";
  system_mode: "default" | "merge" | "drop";
  provider: string;
  judge_enabled: boolean;
}

export type AgentRole = "attacker" | "target" | "judge";
export interface AgentProfile {
  name: string;
  role: AgentRole;
  provider: string;
  model: string;
  prompt_source: "none" | "inline" | "file";
  system_prompt: string;
  system_prompt_file: string;
}
export interface AgentProfileRoleData { active: RoleChoice; profiles: AgentProfile[] }
export interface AgentProfilesResponse { roles: Record<AgentRole, AgentProfileRoleData> }

export interface Preset { name: string; description: string; template: string }
export interface Transform { name: string; description: string; lossy: boolean; reversible: boolean }
export interface Tool {
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
  control?: boolean;
}

export interface AgentControlStatus {
  active: boolean;
  paused: boolean;
  pause_ready?: boolean;
  attacker: string;
  provider: string;
  objective?: string;
}

export interface ComposeResult {
  request: string;
  prompt: string;
  payload: string;
  preset: string;
  transforms: string[];
  system: string;
  max_tokens: number;
  source: string;
}

export interface FireResult extends ComposeResult {
  content: string;
  response: string;
  is_error: boolean;
  verdict: string;
  run_log?: string;
}

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = await r.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export const api = {
  overview: () => j<Overview>("/api/overview"),
  config: () => j<ConfigInfo>("/api/config"),
  settings: () => j<Settings>("/api/settings"),
  models: (profile: string) => j<ModelCatalog>(`/api/models?profile=${encodeURIComponent(profile)}`),
  providers: () => j<ProviderRecord[]>("/api/providers"),
  saveProvider: (name: string, body: Record<string, unknown>) =>
    j<ProviderRecord>(`/api/providers/${encodeURIComponent(name)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  deleteProvider: (name: string) => j<{ ok: boolean }>(`/api/providers/${encodeURIComponent(name)}`, { method: "DELETE" }),
  enableProvider: (name: string) => j<ProviderRecord>(`/api/providers/${encodeURIComponent(name)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: true }),
  }),
  disableProvider: (name: string) => j<ProviderRecord>(`/api/providers/${encodeURIComponent(name)}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: false }),
  }),
  testProvider: (name: string) => j<ProviderTestResult>(`/api/providers/${encodeURIComponent(name)}/test`, { method: "POST" }),
  refreshModels: (name: string) => j<ModelCatalog>(`/api/providers/${encodeURIComponent(name)}/models/refresh`, { method: "POST" }),
  addModel: (name: string, model: string) => j(`/api/providers/${encodeURIComponent(name)}/models`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }),
  }),
  roles: () => j<RoleAssignments>("/api/roles"),
  saveRole: (role: keyof RoleAssignments, body: { profile?: string; provider?: string; model?: string }) => j<RoleChoice>(`/api/roles/${role}`, {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }),
  agentProfiles: () => j<AgentProfilesResponse>("/api/agent-profiles"),
  saveAgentProfile: (role: AgentRole, name: string, body: Omit<AgentProfile, "name" | "role">) =>
    j<AgentProfile>(`/api/agent-profiles/${role}/${encodeURIComponent(name)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  deleteAgentProfile: (role: AgentRole, name: string) => j<{ ok: boolean }>(
    `/api/agent-profiles/${role}/${encodeURIComponent(name)}`, { method: "DELETE" },
  ),
  saveSettings: (body: Record<string, unknown>) =>
    j<Settings>("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  findings: (runs?: string[]) => {
    const qs = runs?.length ? `?runs=${encodeURIComponent(runs.join(","))}` : "";
    return j<Finding[]>(`/api/findings${qs}`);
  },
  findingRuns: () => j<RunSummary[]>("/api/findings/runs"),
  runs: () => j<RunSummary[]>("/api/runs"),
  run: (name: string) => j<RunDetail>(`/api/runs/${encodeURIComponent(name)}`),
  presets: () => j<Preset[]>("/api/presets"),
  transforms: () => j<Transform[]>("/api/transforms"),
  tools: () => j<Tool[]>("/api/tools"),
  agentStatus: () => j<AgentControlStatus>("/api/agent/status"),
  steerAgent: (message: string) => j<{ ok: boolean; queued: number }>("/api/agent/steer", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }),
  }),
  pauseAgent: () => j<AgentControlStatus>("/api/agent/pause", { method: "POST" }),
  resumeAgent: () => j<AgentControlStatus>("/api/agent/resume", { method: "POST" }),
  switchAgentAttacker: (body: { profile?: string; provider?: string; model?: string }) =>
    j<AgentControlStatus>("/api/agent/attacker", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  compose: (body: Record<string, unknown>) =>
    j<ComposeResult>("/api/compose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  fire: (body: Record<string, unknown>) =>
    j<FireResult>("/api/fire", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export interface AgentEvent {
  type: "start" | "round" | "text" | "tool_start" | "tool_result" | "progress" | "feedback" | "usage" | "error" | "done" | "control" | "steer_queued";
  run_log?: string;
  [k: string]: unknown;
}

export async function runAgent(
  body: { objective: string; max_rounds?: number; max_tokens?: number; concurrency?: number; request_delay_ms?: number; enabled_techniques?: string[] },
  onEvent: (ev: AgentEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const r = await fetch("/api/agent/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = frame.startsWith("data:") ? frame.replace(/^data:\s?/, "") : frame;
      if (line) {
        try { onEvent(JSON.parse(line) as AgentEvent); } catch { /* ignore */ }
      }
    }
  }
}

export function verdictKind(label: string | undefined): "bypass" | "partial" | "held" | "neutral" {
  const v = (label || "").toUpperCase();
  if (v === "COMPLIED") return "bypass";
  if (v === "PARTIAL") return "partial";
  if (v === "REFUSED") return "held";
  return "neutral";
}
