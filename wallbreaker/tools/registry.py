from __future__ import annotations

import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..config import Config, Endpoint

ToolHandler = Callable[[dict, "ToolContext"], Awaitable[str]]


@dataclass
class ToolContext:
    config: Config
    cwd: str = "."
    judge_endpoint: Endpoint | None = None
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

    def emit(self, message: str) -> None:
        if self.progress is not None:
            try:
                self.progress(message)
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
        if self.record is not None:
            try:
                self.record(payload, response, label, reason, technique)
            except Exception:
                pass
        if self.vault_enabled:
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
            objective=self.current_objective,
            prompt=payload,
            response=response,
            label=label,
            reason=reason,
            technique=technique,
            attacker_model=self.attacker_model,
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
