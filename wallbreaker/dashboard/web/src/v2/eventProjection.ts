import type { EventEnvelope } from "./types";

type ConversationEntry = {
  role: string;
  type: "objective" | "message" | "tool_call" | "tool_result" | "feedback";
  content?: string;
  name?: string;
  arguments?: unknown;
};

const TELEMETRY_KINDS = new Set(["usage", "lifecycle"]);

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function eventName(event: EventEnvelope): string {
  return String(event.data?.name || event.data?.tool || event.summary || "").toLowerCase();
}

export function inferEventActor(event: Pick<EventEnvelope, "actor" | "kind" | "data" | "summary">): string {
  const explicit = String(event.actor || "").trim().toLowerCase();
  const kind = String(event.kind || "").toLowerCase();
  if (kind === "tool_result" || kind === "result") {
    const name = eventName(event as EventEnvelope);
    if (/query_(image_)?target|continue_target|chat_session/.test(name)) return "target";
    if (/judge|grade|score/.test(name)) return "judge";
    if (explicit && explicit !== "system") return explicit;
    return "tool";
  }
  if (explicit && explicit !== "system") return explicit;
  if (["text", "message", "reasoning", "tool_start", "tool_call", "usage"].includes(kind)) return "attacker";
  if (["feedback", "operator"].includes(kind)) return "operator";
  if (explicit) return explicit;
  return "system";
}

function conversationEntry(event: EventEnvelope): ConversationEntry | null {
  const actor = inferEventActor(event);
  if (event.kind === "message") return { role: actor, type: "message", content: event.text || event.summary || "" };
  if (event.kind === "tool_call") return {
    role: actor,
    type: "tool_call",
    name: String(event.data?.name || event.data?.tool || event.summary || "tool"),
    arguments: event.data?.args || event.data?.arguments,
  };
  if (event.kind === "tool_result") return {
    role: actor,
    type: "tool_result",
    name: String(event.data?.name || event.data?.tool || event.summary || "tool"),
    content: event.text || String(event.data?.content || ""),
  };
  if (["feedback", "operator"].includes(event.kind)) return {
    role: "operator",
    type: "feedback",
    content: event.text || event.summary || "",
  };
  return null;
}

/**
 * Convert verbose transport events into coherent operator activity without
 * changing or discarding the canonical raw stream.
 */
export function projectActivityEvents(events: EventEnvelope[], objective = ""): EventEnvelope[] {
  const projected: EventEnvelope[] = [];
  const ordered = [...events].sort((left, right) => left.sequence - right.sequence);
  let currentRound: number | undefined;

  for (const source of ordered) {
    const sourceRound = source.round ?? (typeof source.data?.round === "number" ? source.data.round : undefined);
    if (source.kind === "round" && sourceRound) currentRound = sourceRound;
    const correlatedSource = sourceRound || !currentRound ? source : { ...source, round: currentRound };
    const actor = inferEventActor(correlatedSource);
    if (correlatedSource.kind === "text") {
      const previous = projected[projected.length - 1];
      if (previous?.kind === "message" && previous.actor === actor && previous.round === correlatedSource.round) {
        previous.text = `${previous.text || ""}${correlatedSource.text || correlatedSource.summary || ""}`;
        previous.raw = [...(Array.isArray(previous.raw) ? previous.raw : [previous.raw]), correlatedSource.raw];
      } else {
        projected.push({
          ...correlatedSource,
          kind: "message",
          actor,
          summary: actor === "attacker" ? "Attacker response" : `${actor} message`,
          text: correlatedSource.text || correlatedSource.summary,
          raw: [correlatedSource.raw],
        });
      }
      continue;
    }

    if (correlatedSource.kind === "usage") {
      const usage = record(correlatedSource.data);
      const prior = [...projected].reverse().find((item) => item.kind === "message" && inferEventActor(item) === "attacker");
      if (prior) {
        const inputTokens = correlatedSource.input_tokens ?? Number(usage.input_tokens ?? usage.input);
        const outputTokens = correlatedSource.output_tokens ?? Number(usage.output_tokens ?? usage.output);
        prior.input_tokens = Number.isFinite(inputTokens) ? inputTokens : undefined;
        prior.output_tokens = Number.isFinite(outputTokens) ? outputTokens : undefined;
        prior.data = { ...(prior.data || {}), usage: correlatedSource.raw };
      }
      continue;
    }

    if (TELEMETRY_KINDS.has(correlatedSource.kind)) continue;

    let kind = correlatedSource.kind;
    let summary = correlatedSource.summary;
    if (kind === "tool_start") { kind = "tool_call"; summary ||= String(correlatedSource.data?.name || "Tool call"); }
    if (kind === "start") summary ||= "Run started";
    if (kind === "round") summary ||= `Round ${correlatedSource.round || correlatedSource.data?.round || ""}`.trim();
    if (kind === "done") summary ||= "Run completed";
    projected.push({ ...correlatedSource, kind, actor, summary });
  }

  const conversation: ConversationEntry[] = objective.trim()
    ? [{ role: "operator", type: "objective", content: objective.trim() }]
    : [];
  return projected.map((event) => {
    const entry = conversationEntry(event);
    if (entry) conversation.push(entry);
    return {
      ...event,
      data: { ...(event.data || {}), conversation: conversation.map((item) => ({ ...item })) },
    };
  });
}

/** Attach the best conversation snapshot to each untouched raw event. */
export function correlateRawEvents(events: EventEnvelope[], objective = ""): EventEnvelope[] {
  const activity = projectActivityEvents(events, objective);
  return [...events]
    .sort((left, right) => left.sequence - right.sequence)
    .map((event) => {
      const correlated = [...activity].reverse().find((item) => item.sequence <= event.sequence);
      return {
        ...event,
        actor: inferEventActor(event),
        data: {
          ...(event.data || {}),
          conversation: correlated?.data?.conversation || [],
        },
      };
    });
}
