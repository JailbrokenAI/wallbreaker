from __future__ import annotations

import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..config import Config, Endpoint

ToolHandler = Callable[[dict, "ToolContext"], Awaitable[str]]


# ---------------------------------------------------------------------------
# TG2 — ToolContext sub-contexts  (item B / R-B1)
# ---------------------------------------------------------------------------

@dataclass
class EngagementContext:
    """Fields that describe the current red-team engagement target and objective."""
    current_objective: str = ""
    attacker_model: str = ""
    vault_enabled: bool = True
    target_thread: list = field(default_factory=list)
    target_system: str | None = None
    target_reasoning: str = ""  # includes recovered CoT (Method 1/5/6)
    target_reasoning_details: list = field(default_factory=list)
    # CoT recovery defaults for query_target / continue_target (overridable per-call)
    recover_cot: str = "auto"  # auto|off|details|deep_think|stolen_thoughts|all
    cot_weak_model: str = ""  # Method 5 weak sibling model id


@dataclass
class IOContext:
    """Fields that wire tool I/O sinks: progress, record, structured events, logging."""
    progress: Callable[[str], None] | None = None
    record: Callable[[str, str, str, str, str], None] | None = None
    # structured live-run sink (TUI renders one self-updating attack panel); when
    # absent, RunHandle degrades to plain `progress` strings so headless/CLI/tests
    # keep working unchanged.
    run_events: Callable[[dict], None] | None = None
    _run_seq: int = 0
    # the live hands-on target conversation (query_target opens it, continue_target pushes)
    target_thread: list = field(default_factory=list)
    target_system: str | None = None
    target_reasoning: str = ""  # the target's reasoning/CoT from its last reply
    # objective of the active engagement, so auto-saved breaks fold under the right folder
    current_objective: str = ""
    # attacker/brain model id that authored the winning prompt (for vault provenance)
    attacker_model: str = ""
    # auto-save every COMPLIED/PARTIAL verdict into the BreakVault (library/breaks/)
    vault_enabled: bool = True
    # confine read_file to cwd (defence-in-depth against arbitrary local file read, audit SEC-5).
    # Off by default so the local CLI/TUI operator keeps full-filesystem reads; the dashboard
    # registry builder turns it ON so a browser-driven agent can't exfiltrate ~/.env, keys, etc.
    confine_reads: bool = False
    # host sink that logs EVERY tool execution (brain loop AND slash commands) to the run log
    tool_logger: Callable[[str, dict, str, bool], None] | None = None


# ---------------------------------------------------------------------------
# ToolContext  (thin envelope — item B / R-B1, R-B2)
# ---------------------------------------------------------------------------

class ToolContext:
    """Thin context envelope passed to every tool handler.

    Direct attributes: config, cwd, judge_endpoint, confine_reads, engagement, io.
    All legacy field names (current_objective, attacker_model, vault_enabled, target_thread,
    target_system, target_reasoning, progress, record, run_events, tool_logger) are preserved
    as delegating properties so zero tool signatures change and the full existing test suite
    remains green (R-B2 / SP-DI5).

    Backward-compatible __init__: accepts all old keyword arguments directly and routes them
    to the appropriate sub-context, so existing ToolContext(config=..., record=..., progress=...)
    call sites continue to work with no changes.
    """

    def __init__(
        self,
        config: Config,
        cwd: str = ".",
        judge_endpoint: Endpoint | None = None,
        confine_reads: bool = False,
        # Legacy IO kwargs (routed to IOContext)
        progress: Callable[[str], None] | None = None,
        record: Callable[[str, str, str, str, str], None] | None = None,
        run_events: Callable[[dict], None] | None = None,
        tool_logger: Callable[[str, dict, str, bool], None] | None = None,
        # Legacy engagement kwargs (routed to EngagementContext)
        current_objective: str = "",
        attacker_model: str = "",
        vault_enabled: bool = True,
        target_thread: list | None = None,
        target_system: str | None = None,
        target_reasoning: str = "",
        # Sub-context objects (override individual kwargs if provided)
        engagement: EngagementContext | None = None,
        io: IOContext | None = None,
    ) -> None:
        self.config = config
        self.cwd = cwd
        self.judge_endpoint = judge_endpoint
        self.confine_reads = confine_reads
        self._run_seq: int = 0
        # Build sub-contexts
        self.engagement = engagement or EngagementContext(
            current_objective=current_objective,
            attacker_model=attacker_model,
            vault_enabled=vault_enabled,
            target_thread=target_thread if target_thread is not None else [],
            target_system=target_system,
            target_reasoning=target_reasoning,
        )
        self.io = io or IOContext(
            progress=progress,
            record=record,
            run_events=run_events,
            tool_logger=tool_logger,
        )

    # ------------------------------------------------------------------
    # EngagementContext delegating properties (R-B2)
    # ------------------------------------------------------------------

    @property
    def current_objective(self) -> str:
        return self.engagement.current_objective

    @current_objective.setter
    def current_objective(self, v: str) -> None:
        self.engagement.current_objective = v

    @property
    def attacker_model(self) -> str:
        return self.engagement.attacker_model

    @attacker_model.setter
    def attacker_model(self, v: str) -> None:
        self.engagement.attacker_model = v

    @property
    def vault_enabled(self) -> bool:
        return self.engagement.vault_enabled

    @vault_enabled.setter
    def vault_enabled(self, v: bool) -> None:
        self.engagement.vault_enabled = v

    @property
    def target_thread(self) -> list:
        return self.engagement.target_thread

    @target_thread.setter
    def target_thread(self, v: list) -> None:
        self.engagement.target_thread = v

    @property
    def target_system(self) -> str | None:
        return self.engagement.target_system

    @target_system.setter
    def target_system(self, v: str | None) -> None:
        self.engagement.target_system = v

    @property
    def target_reasoning(self) -> str:
        return self.engagement.target_reasoning

    @target_reasoning.setter
    def target_reasoning(self, v: str) -> None:
        self.engagement.target_reasoning = v

    @property
    def target_reasoning_details(self) -> list:
        return self.engagement.target_reasoning_details

    @target_reasoning_details.setter
    def target_reasoning_details(self, v: list) -> None:
        self.engagement.target_reasoning_details = v if v is not None else []

    @property
    def recover_cot(self) -> str:
        return self.engagement.recover_cot

    @recover_cot.setter
    def recover_cot(self, v: str) -> None:
        self.engagement.recover_cot = str(v or "auto")

    @property
    def cot_weak_model(self) -> str:
        return self.engagement.cot_weak_model

    @cot_weak_model.setter
    def cot_weak_model(self, v: str) -> None:
        self.engagement.cot_weak_model = str(v or "")

    # ------------------------------------------------------------------
    # IOContext delegating properties (R-B2)
    # ------------------------------------------------------------------

    @property
    def progress(self) -> Callable[[str], None] | None:
        return self.io.progress

    @progress.setter
    def progress(self, v: Callable[[str], None] | None) -> None:
        self.io.progress = v

    @property
    def record(self) -> Callable[[str, str, str, str, str], None] | None:
        return self.io.record

    @record.setter
    def record(self, v: Callable[[str, str, str, str, str], None] | None) -> None:
        self.io.record = v

    @property
    def run_events(self) -> Callable[[dict], None] | None:
        return self.io.run_events

    @run_events.setter
    def run_events(self, v: Callable[[dict], None] | None) -> None:
        self.io.run_events = v

    @property
    def tool_logger(self) -> Callable[[str, dict, str, bool], None] | None:
        return self.io.tool_logger

    @tool_logger.setter
    def tool_logger(self, v: Callable[[str, dict, str, bool], None] | None) -> None:
        self.io.tool_logger = v

    # ------------------------------------------------------------------
    # Methods (delegate through sub-contexts where appropriate, R-B2)
    # ------------------------------------------------------------------

    def emit(self, message: str) -> None:
        if self.io.progress is not None:
            try:
                self.io.progress(message)
            except Exception:
                pass

    def run(
        self,
        label: str,
        total: int,
        target: str | None = None,
        objective: str | None = None,
    ) -> "RunHandle":
        """Open a structured multi-step run (PAIR sweep, crescendo, survey...).

        Use as a context manager:
            with ctx.run("PAIR sweep", total=len(objs), target=...) as run:
                for i, obj in enumerate(objs, 1):
                    run.step(label=obj[:30], verdict=label, score=score)
        """
        self._run_seq += 1
        return RunHandle(self, self._run_seq, label, total, target, objective)

    def record_verdict(
        self, payload: str, response: str, label: str, reason: str, technique: str
    ) -> None:
        """Report a graded fire to the host (run log + ASR) if a sink is wired.

        Every COMPLIED/PARTIAL verdict also auto-files into the BreakVault
        (library/breaks/<target>/<objective>/) so a working prompt is never lost.
        """
        if self.io.record is not None:
            try:
                self.io.record(payload, response, label, reason, technique)
            except Exception:
                pass
        if self.engagement.vault_enabled:
            try:
                self._vault_save(payload, response, label, reason, technique)
            except Exception:
                pass

    def _vault_save(
        self, payload: str, response: str, label: str, reason: str, technique: str
    ) -> None:
        from .. import vault

        if not vault.is_win(label) or not str(payload or "").strip():
            return
        target = ""
        if self.config is not None and self.config.target is not None:
            target = self.config.target.model or ""
        vault.BreakVault(cwd=self.cwd).save(
            target=target,
            objective=self.engagement.current_objective,
            prompt=payload,
            response=response,
            label=label,
            reason=reason,
            technique=technique,
            attacker_model=self.engagement.attacker_model,
        )


class RunHandle:
    """A live, multi-step attack run. Emits structured events to ctx.run_events
    when wired (the TUI renders one self-updating panel), else falls back to plain
    ctx.emit() strings (the recommend_transforms `[i/total]` contract included)."""

    def __init__(self, ctx, run_id, label, total, target=None, objective=None):
        self._ctx = ctx
        self.id = run_id
        self.label = label
        self.total = total
        self.target = target
        self.objective = objective
        self._i = 0
        self._done = False

    def _send(self, event: dict) -> None:
        sink = self._ctx.run_events
        if sink is not None:
            try:
                sink(event)
                return
            except Exception:
                pass
        self._ctx.emit(self._fallback(event))

    @staticmethod
    def _fallback(event: dict) -> str:
        ev = event.get("ev")
        if ev == "start":
            tgt = f" vs {event['target']}" if event.get("target") else ""
            return f"{event.get('label', 'run')}: {event.get('total', 0)} steps{tgt}"
        if ev == "step":
            score = event.get("score")
            sc = f"({score})" if score is not None else ""
            cot = " +CoT" if event.get("cot") else ""
            return (
                f"  [{event.get('i')}/{event.get('total', '?')}] "
                f"{event.get('label', '')}: {event.get('verdict', '')}{sc}{cot}"
            )
        if ev == "note":
            return f"  {event.get('text', '')}"
        if ev == "done":
            return event.get("summary", "done")
        return ""

    def __enter__(self) -> "RunHandle":
        self._send({
            "ev": "start", "id": self.id, "label": self.label,
            "total": self.total, "target": self.target, "objective": self.objective,
        })
        return self

    def step(self, label="", verdict="", score=None, cot=False, dt=None, i=None, note=""):
        if i is None:
            self._i += 1
            i = self._i
        else:
            self._i = i
        event = {
            "ev": "step", "id": self.id, "i": i, "total": self.total,
            "label": label, "verdict": verdict, "score": score, "cot": bool(cot),
        }
        if dt is not None:
            event["dt"] = dt
        if note:
            event["note"] = note
        self._send(event)
        return i

    def note(self, text: str) -> None:
        self._send({"ev": "note", "id": self.id, "text": text})

    def done(self, summary="", best=None) -> None:
        if self._done:
            return
        self._done = True
        self._send({"ev": "done", "id": self.id, "summary": summary, "best": best})

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None and not self._done:
            self._done = True
            self._send({
                "ev": "done", "id": self.id,
                "summary": f"error: {exc}", "error": True,
            })
        elif not self._done:
            self.done()
        return False


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: ToolHandler

    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class ToolRegistry:
    ctx: ToolContext
    tools: dict[str, Tool] = field(default_factory=dict)

    def add(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: ToolHandler,
    ) -> None:
        self.tools[name] = Tool(name, description, parameters, handler)

    def specs(self) -> list[dict]:
        return [t.spec() for t in self.tools.values()]

    def names(self) -> list[str]:
        return list(self.tools)

    def remove(self, name: str) -> bool:
        """Drop a tool from the registry (used by the dashboard tool-exposure policy)."""
        return self.tools.pop(name, None) is not None

    async def execute(self, name: str, args: dict) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(f"Unknown tool: {name}", is_error=True)
        # REL-2: scope provider lifetime to this tool call. build_provider() calls made by
        # the handler (and its child tasks) are tracked and aclose()d here on exit, so pooled
        # httpx.AsyncClients don't leak across rounds of an autonomous run. A provider reused
        # within the call (e.g. best_of_n's target) stays pooled until the call ends.
        from ..providers.factory import provider_scope

        async with provider_scope():
            try:
                output = await tool.handler(args or {}, self.ctx)
                result = ToolResult(output)
            except Exception as exc:  # noqa: BLE001
                detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
                result = ToolResult(f"Tool '{name}' raised: {detail}", is_error=True)
            if self.ctx.tool_logger is not None:
                try:
                    self.ctx.tool_logger(name, args or {}, result.content, result.is_error)
                except Exception:
                    pass
        return result
