import type {
  ApiResult,
  ArsenalItem,
  Capability,
  ComposePayload,
  ComposeResult,
  EventEnvelope,
  ExecutionStatus,
  ExecutionMode,
  ExecutionSummary,
  FindingRecord,
  HistoryEvent,
  ProviderRecord,
  RunSummary,
  SettingsRecord,
} from "./types";

class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let message = response.statusText || `Request failed (${response.status})`;
    try {
      const body = await response.json() as { detail?: string; message?: string };
      message = body.detail || body.message || message;
    } catch {
      // The endpoint may return an empty or plain-text error.
    }
    throw new HttpError(response.status, message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

function text(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function number(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function executionStatus(value: unknown): ExecutionStatus {
  const candidate = text(value).toLowerCase();
  if (["queued", "running", "pausing", "paused", "succeeded", "failed", "cancelled"].includes(candidate)) {
    return candidate as ExecutionStatus;
  }
  if (candidate === "completed" || candidate === "done") return "succeeded";
  if (candidate === "error") return "failed";
  return "queued";
}

function normalizeExecution(value: unknown, source: "v2" | "legacy" = "v2"): ExecutionSummary {
  const row = object(value);
  return {
    ...row,
    id: text(row.id || row.execution_id || row.run_id || row.name),
    run_id: text(row.run_id || row.name) || undefined,
    title: text(row.title || row.objective || row.capability_id) || undefined,
    objective: text(row.objective) || undefined,
    status: executionStatus(row.status),
    current_round: number(row.current_round || row.round),
    max_rounds: number(row.max_rounds || row.rounds),
    elapsed_ms: number(row.elapsed_ms || row.duration_ms),
    input_tokens: number(row.input_tokens),
    output_tokens: number(row.output_tokens),
    source,
  };
}

function normalizeEvent(value: unknown, executionId: string, index: number): EventEnvelope {
  const row = object(value);
  const data = object(row.data);
  const request = object(row.request);
  const endpoint = object(request.endpoint);
  const kind = text(row.kind || row.type || row.event || "system").toLowerCase();
  const actor = text(row.actor || data.actor || row.role || row.source || endpoint.provider) || undefined;
  const label = text(row.verdict || row.label || data.verdict) || undefined;
  const strategy = text(row.strategy || row.technique || data.strategy || data.technique) || undefined;
  const summary = text(row.summary || row.message || data.summary || data.message || row.detail || row.operation || row.tool || row.name || data.tool || data.state) || undefined;
  const response = text(row.text || row.response || row.content || data.text || data.response || data.content) || undefined;
  const sequence = number(row.sequence || row.seq) || index + 1;
  return {
    version: number(row.version) || 1,
    id: text(row.id || row.event_id) || `${executionId}:${sequence}`,
    sequence,
    execution_id: text(row.execution_id) || executionId,
    run_id: text(row.run_id) || undefined,
    timestamp: text(row.timestamp || row.ts || row.time) || new Date(0).toISOString(),
    kind,
    actor,
    strategy,
    round: number(row.round || data.round || data.current_round),
    verdict: label,
    summary,
    text: response,
    latency_ms: number(row.latency_ms || row.duration_ms || data.latency_ms),
    input_tokens: number(row.input_tokens || data.input_tokens),
    output_tokens: number(row.output_tokens || data.output_tokens),
    data: Object.keys(data).length ? data : undefined,
    raw: value,
  };
}

function capabilityFromLegacy(kind: ArsenalItem["kind"], value: unknown): Capability {
  const row = object(value);
  const name = text(row.name);
  const category = kind === "tool" ? "Tools" : kind === "preset" ? "Presets" : "Transforms";
  return {
    id: `${kind}.${name}`,
    title: name.replace(/[_-]+/g, " "),
    description: text(row.description),
    category,
    execution_mode: kind === "tool" ? "queued" : "immediate",
    input_schema: kind === "tool" ? object(row.parameters) : undefined,
    legacy_only: true,
  };
}

function listPayload(value: unknown, keys: string[]): unknown[] {
  if (Array.isArray(value)) return value;
  const row = object(value);
  for (const key of keys) if (Array.isArray(row[key])) return row[key] as unknown[];
  return [];
}

export const v2Api = {
  async capabilities(): Promise<ApiResult<Capability[]>> {
    try {
      const body = await request<unknown>("/api/v2/capabilities");
      const capabilities = listPayload(body, ["capabilities", "items"]).map((item) => {
        const row = object(item);
        const schema = object(row.input_schema || row.argument_schema);
        return {
          ...row,
          id: text(row.id || row.name),
          title: text(row.title || row.name || row.id),
          category: text(row.category || "Other"),
          input_schema: Object.keys(schema).length ? schema : undefined,
        } as Capability;
      }).filter((item) => item.id);
      return { data: capabilities, source: "v2" };
    } catch {
      const [presets, transforms, tools] = await Promise.all([
        request<unknown[]>("/api/presets").catch(() => []),
        request<unknown[]>("/api/transforms").catch(() => []),
        request<unknown[]>("/api/tools").catch(() => []),
      ]);
      return {
        data: [
          ...presets.map((item) => capabilityFromLegacy("preset", item)),
          ...transforms.map((item) => capabilityFromLegacy("transform", item)),
          ...tools.map((item) => capabilityFromLegacy("tool", item)),
        ],
        source: "legacy",
      };
    }
  },

  async executions(): Promise<ApiResult<ExecutionSummary[]>> {
    try {
      const body = await request<unknown>("/api/v2/executions");
      return {
        data: listPayload(body, ["executions", "items"]).map((item) => normalizeExecution(item)),
        source: "v2",
      };
    } catch {
      const [status, runs] = await Promise.all([
        request<Record<string, unknown>>("/api/agent/status").catch(() => ({})),
        request<RunSummary[]>("/api/runs").catch(() => []),
      ]);
      const statusRecord = object(status);
      const active = statusRecord.active ? [{
        id: "legacy-active",
        title: text(statusRecord.objective) || "Active engagement",
        objective: text(statusRecord.objective) || undefined,
        status: statusRecord.paused ? "paused" as const : "running" as const,
        attacker: text(statusRecord.attacker) || undefined,
        source: "legacy" as const,
      }] : [];
      const completed = runs.map((run) => normalizeExecution({
        id: run.name,
        run_id: run.name,
        title: run.name,
        status: "succeeded",
        created_at: run.time,
        ...run.models,
      }, "legacy"));
      return { data: [...active, ...completed], source: "legacy" };
    }
  },

  execution: async (id: string) => normalizeExecution(
    await request<unknown>(`/api/v2/executions/${encodeURIComponent(id)}`),
  ),

  async legacyEvents(run: string): Promise<EventEnvelope[]> {
    const body = await request<Record<string, unknown>>(`/api/runs/${encodeURIComponent(run)}`);
    const records = Array.isArray(body.records) ? body.records : [];
    return records.map((record, index) => normalizeEvent(record, run, index));
  },

  async streamEvents(
    executionId: string,
    after: number,
    onEvent: (event: EventEnvelope) => void,
    signal: AbortSignal,
  ): Promise<void> {
    const url = `/api/v2/executions/${encodeURIComponent(executionId)}/events?after=${after}`;
    const response = await fetch(url, { signal, headers: { Accept: "text/event-stream" } });
    if (!response.ok || !response.body) throw new HttpError(response.status, response.statusText);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (!signal.aborted) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame.split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trim())
          .join("\n");
        if (data) {
          try { onEvent(normalizeEvent(JSON.parse(data), executionId, after)); } catch { /* ignore malformed frames */ }
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  },

  createExecution: (capabilityId: string, args: Record<string, unknown>, mode: ExecutionMode) =>
    request<ExecutionSummary>("/api/v2/executions", json({ capability_id: capabilityId, args, mode })),

  pause: async (execution: ExecutionSummary) => execution.source === "legacy"
    ? request<ExecutionSummary>("/api/agent/pause", { method: "POST" }).then((value) => normalizeExecution(value, "legacy"))
    : request<ExecutionSummary>(`/api/v2/executions/${encodeURIComponent(execution.id)}/pause`, { method: "POST" }).then((value) => normalizeExecution(value)),

  resume: async (execution: ExecutionSummary) => execution.source === "legacy"
    ? request<ExecutionSummary>("/api/agent/resume", { method: "POST" }).then((value) => normalizeExecution(value, "legacy"))
    : request<ExecutionSummary>(`/api/v2/executions/${encodeURIComponent(execution.id)}/resume`, { method: "POST" }).then((value) => normalizeExecution(value)),

  cancel: async (execution: ExecutionSummary) => {
    if (execution.source === "legacy") throw new Error("Hard cancellation requires the V2 execution service.");
    return request<ExecutionSummary>(`/api/v2/executions/${encodeURIComponent(execution.id)}/cancel`, { method: "POST" }).then((value) => normalizeExecution(value));
  },

  switchAttacker: (execution: ExecutionSummary, body: { provider?: string; model?: string; profile?: string }) =>
    request<ExecutionSummary>(`/api/v2/executions/${encodeURIComponent(execution.id)}/attacker`, json(body)).then((value) => normalizeExecution(value)),

  steer: async (execution: ExecutionSummary, message: string) => execution.source === "legacy"
    ? request<{ ok: boolean }>("/api/agent/steer", json({ message }))
    : request<{ ok: boolean }>(`/api/v2/executions/${encodeURIComponent(execution.id)}/steer`, json({ message })),

  compose: (body: ComposePayload) => request<ComposeResult>("/api/compose", json(body)),
  fire: (body: ComposePayload & { source?: string }) => request<ComposeResult>("/api/fire", json(body)),
  presets: () => request<Array<Record<string, unknown>>>("/api/presets"),
  transforms: () => request<Array<Record<string, unknown>>>("/api/transforms"),
  tools: () => request<Array<Record<string, unknown>>>("/api/tools"),
  runs: () => request<RunSummary[]>("/api/runs"),
  run: (name: string) => request<Record<string, unknown>>(`/api/runs/${encodeURIComponent(name)}`),
  findings: (runs?: string[]) => request<FindingRecord[]>(`/api/findings${runs?.length ? `?runs=${encodeURIComponent(runs.join(","))}` : ""}`),
  providers: () => request<ProviderRecord[]>("/api/providers"),
  testProvider: (name: string) => request<Record<string, unknown>>(`/api/providers/${encodeURIComponent(name)}/test`, { method: "POST" }),
  settings: () => request<SettingsRecord>("/api/settings"),
  saveSettings: (body: SettingsRecord) => request<SettingsRecord>("/api/settings", json(body)),
  historyRuns: () => request<{ items: Array<Record<string, unknown>>; total: number }>("/api/v2/history/runs"),
  historyEvents: (filters: Record<string, string | number | undefined>) => {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => { if (value !== undefined && value !== "") query.set(key, String(value)); });
    return request<{ items: HistoryEvent[]; total: number; limit: number; offset: number }>(`/api/v2/history/events?${query.toString()}`);
  },
  rebuildHistory: () => request<Record<string, unknown>>("/api/v2/history/rebuild", { method: "POST" }),
};

export function arsenalItems(
  presets: Array<Record<string, unknown>>,
  transforms: Array<Record<string, unknown>>,
  tools: Array<Record<string, unknown>>,
): ArsenalItem[] {
  const map = (kind: ArsenalItem["kind"], rows: Array<Record<string, unknown>>) => rows.map((row) => ({
    name: text(row.name),
    description: text(row.description),
    kind,
    detail: row,
  }));
  return [...map("preset", presets), ...map("transform", transforms), ...map("tool", tools)];
}

export function eventFromUnknown(value: unknown, executionId: string, index: number): EventEnvelope {
  return normalizeEvent(value, executionId, index);
}
