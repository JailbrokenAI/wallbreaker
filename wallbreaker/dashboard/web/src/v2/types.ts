export type V2Route =
  | "agent"
  | "live"
  | "compose"
  | "workflows"
  | "arsenal"
  | "findings"
  | "runs"
  | "reports"
  | "models"
  | "settings";

export type ExecutionStatus =
  | "queued"
  | "running"
  | "pausing"
  | "paused"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface ExecutionSummary {
  id: string;
  run_id?: string;
  capability_id?: string;
  title?: string;
  objective?: string;
  status: ExecutionStatus;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
  current_round?: number;
  max_rounds?: number;
  attacker?: string;
  target?: string;
  judge?: string;
  elapsed_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  budget_used?: number;
  budget_limit?: number;
  source?: "v2" | "legacy";
  [key: string]: unknown;
}

export type EventKind =
  | "system"
  | "text"
  | "reasoning"
  | "tool"
  | "verdict"
  | "image"
  | "artifact"
  | "error"
  | "control"
  | string;

export interface EventEnvelope {
  version: number;
  id: string;
  sequence: number;
  execution_id: string;
  run_id?: string;
  timestamp: string;
  kind: EventKind;
  actor?: string;
  strategy?: string;
  round?: number;
  verdict?: string;
  summary?: string;
  text?: string;
  latency_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  data?: Record<string, unknown>;
  raw?: unknown;
}

export interface CapabilityProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  items?: CapabilityProperty;
}

export interface Capability {
  id: string;
  title: string;
  description?: string;
  category: string;
  execution_mode?: "immediate" | "interactive" | "background" | "queued" | string;
  cancellable?: boolean;
  progress?: string;
  input_schema?: {
    type?: string;
    properties?: Record<string, CapabilityProperty>;
    required?: string[];
  };
  defaults?: Record<string, unknown>;
  result_types?: string[];
  legacy_only?: boolean;
}

export type ExecutionMode = "interactive" | "background";

export interface RunSummary {
  name: string;
  time?: string;
  size?: number;
  records?: number;
  hits?: number;
  findings?: number;
  models?: Record<string, string | boolean | undefined>;
}

export interface HistoryEvent {
  id: number;
  run_name: string;
  source_line: number;
  sequence: number;
  timestamp: string;
  event_type: string;
  actor: string;
  technique: string;
  verdict: string;
  latency_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  cost?: number;
  execution_id?: string;
  round_id?: string;
  inference_id?: string;
  tool_id?: string;
  structured_json: string;
}

export interface FindingRecord {
  id?: string;
  run?: string;
  ts?: string;
  label?: string;
  technique?: string;
  payload?: string;
  response?: string;
  reason?: string;
  category?: string;
  raw?: string;
  [key: string]: unknown;
}

export interface ArsenalItem {
  name: string;
  description?: string;
  kind: "preset" | "transform" | "tool";
  detail?: unknown;
}

export interface ProviderRecord {
  name: string;
  model?: string;
  protocol?: string;
  base_url?: string;
  modality?: string;
  enabled?: boolean;
  reasoning?: boolean;
  timeout?: number;
  has_api_key?: boolean;
  [key: string]: unknown;
}

export interface ComposePayload {
  request: string;
  preset?: string;
  transforms?: string[];
  system?: string;
  max_tokens?: number;
}

export interface ConversationTurn {
  index: number;
  request: string;
  prompt: string;
  payload: string;
  response: string;
  verdict?: string;
  is_error?: boolean;
  preset?: string;
  transforms?: string[];
  continuation: boolean;
}

export interface ConsoleConversation {
  active: boolean;
  turn_count: number;
  turns: ConversationTurn[];
  run_log: string;
  archived_run?: string;
}

export interface ComposeResult extends ComposePayload {
  prompt?: string;
  payload: string;
  source?: string;
  response?: string;
  verdict?: string;
  is_error?: boolean;
  run_log?: string;
  turn?: ConversationTurn;
  conversation?: ConsoleConversation;
}

export interface SettingsRecord {
  agent?: {
    max_rounds?: number;
    max_tokens?: number;
    concurrency?: number;
    request_delay_ms?: number;
  };
  [key: string]: unknown;
}

export interface ApiResult<T> {
  data: T;
  source: "v2" | "legacy";
}
