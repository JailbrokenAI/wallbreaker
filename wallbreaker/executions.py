from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
VALID_MODES = {"interactive", "background"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclasses.dataclass(frozen=True)
class ExecutionEvent:
    execution_id: str
    sequence: int
    type: str
    timestamp: str
    data: dict[str, Any]
    version: int = 1

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class ExecutionContext:
    """Control surface passed to a server-owned execution runner."""

    def __init__(self, execution: "Execution") -> None:
        self.execution = execution

    def emit(self, event_type: str, **data: Any) -> ExecutionEvent:
        return self.execution.emit(event_type, **data)

    async def checkpoint(self) -> None:
        """Pause at a safe boundary, if requested, or raise on cancellation."""
        if self.execution.cancel_requested:
            raise asyncio.CancelledError
        if not self.execution.pause_requested:
            return
        self.execution.status = "paused"
        self.execution.updated_at = _now()
        self.execution.emit("control", state="paused")
        await self.execution.resume_event.wait()
        if self.execution.cancel_requested:
            raise asyncio.CancelledError
        self.execution.status = "running"
        self.execution.updated_at = _now()
        self.execution.emit("control", state="running")

    def drain_feedback(self) -> list[str]:
        values = self.execution.feedback[:]
        self.execution.feedback.clear()
        return values


Runner = Callable[[ExecutionContext], Awaitable[dict[str, Any] | None]]


@dataclasses.dataclass
class Execution:
    capability_id: str
    args: dict[str, Any]
    mode: str
    id: str = dataclasses.field(default_factory=lambda: uuid4().hex)
    status: str = "queued"
    created_at: str = dataclasses.field(default_factory=_now)
    updated_at: str = dataclasses.field(default_factory=_now)
    run_id: str = ""
    result: dict[str, Any] | None = None
    error: str = ""
    events: list[ExecutionEvent] = dataclasses.field(default_factory=list)
    feedback: list[str] = dataclasses.field(default_factory=list)
    pause_requested: bool = False
    cancel_requested: bool = False
    resume_event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event, repr=False)
    task: asyncio.Task | None = dataclasses.field(default=None, repr=False)
    condition: asyncio.Condition = dataclasses.field(default_factory=asyncio.Condition, repr=False)
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)
    _sequence: int = dataclasses.field(default=0, repr=False)

    def __post_init__(self) -> None:
        self.resume_event.set()

    def emit(self, event_type: str, **data: Any) -> ExecutionEvent:
        self._sequence += 1
        event = ExecutionEvent(
            execution_id=self.id,
            sequence=self._sequence,
            type=event_type,
            timestamp=_now(),
            data=data,
        )
        self.events.append(event)
        self.updated_at = event.timestamp

        async def wake() -> None:
            async with self.condition:
                self.condition.notify_all()

        try:
            asyncio.get_running_loop().create_task(wake())
        except RuntimeError:
            pass
        return event

    def as_dict(self, *, include_args: bool = True) -> dict[str, Any]:
        data = {
            "id": self.id,
            "capability_id": self.capability_id,
            "mode": self.mode,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_id": self.run_id,
            "result": self.result,
            "error": self.error,
            "event_count": len(self.events),
            "pause_requested": self.pause_requested,
            "cancel_requested": self.cancel_requested,
            "metadata": self.metadata,
            "title": str(self.metadata.get("title") or self.args.get("objective") or self.capability_id),
            "objective": str(self.args.get("objective") or ""),
        }
        for key in (
            "current_round", "max_rounds", "max_tokens", "attacker", "target",
            "judge", "provider", "input_tokens", "output_tokens", "verdict",
            "technique", "latency_ms",
        ):
            if key in self.metadata:
                data[key] = self.metadata[key]
        if include_args:
            data["args"] = self.args
        return data


class ExecutionManager:
    """Owns execution lifecycles independently of HTTP connections."""

    def __init__(self, *, background_concurrency: int = 2, max_events: int = 50_000) -> None:
        self.executions: dict[str, Execution] = {}
        self.background_semaphore = asyncio.Semaphore(max(1, background_concurrency))
        self.interactive_semaphore = asyncio.Semaphore(1)
        self.max_events = max(100, max_events)

    def get(self, execution_id: str) -> Execution | None:
        return self.executions.get(execution_id)

    def list(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        values = list(reversed(self.executions.values()))
        if status:
            values = [item for item in values if item.status == status]
        return [item.as_dict() for item in values[: max(1, min(limit, 1000))]]

    def create(
        self,
        capability_id: str,
        args: dict[str, Any],
        runner: Runner,
        *,
        mode: str = "background",
    ) -> Execution:
        if mode not in VALID_MODES:
            raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")
        execution = Execution(capability_id=capability_id, args=dict(args), mode=mode)
        self.executions[execution.id] = execution
        execution.emit("lifecycle", state="queued")
        execution.task = asyncio.create_task(self._run(execution, runner))
        return execution

    async def _run(self, execution: Execution, runner: Runner) -> None:
        semaphore = (
            self.interactive_semaphore
            if execution.mode == "interactive"
            else self.background_semaphore
        )
        try:
            async with semaphore:
                if execution.cancel_requested:
                    raise asyncio.CancelledError
                execution.status = "running"
                execution.emit("lifecycle", state="running")
                result = await runner(ExecutionContext(execution))
                if execution.cancel_requested:
                    raise asyncio.CancelledError
                execution.result = result or {}
                execution.status = "succeeded"
                execution.emit("lifecycle", state="succeeded", result=execution.result)
        except asyncio.CancelledError:
            execution.status = "cancelled"
            execution.emit("lifecycle", state="cancelled")
        except Exception as exc:  # noqa: BLE001 - execution errors are event data
            execution.status = "failed"
            execution.error = f"{type(exc).__name__}: {exc}"
            execution.emit("error", error=execution.error)
            execution.emit("lifecycle", state="failed")
        finally:
            execution.updated_at = _now()
            execution.resume_event.set()
            if len(execution.events) > self.max_events:
                execution.events[:] = execution.events[-self.max_events :]
            async with execution.condition:
                execution.condition.notify_all()

    def pause(self, execution_id: str) -> Execution:
        execution = self._active(execution_id)
        execution.pause_requested = True
        execution.resume_event.clear()
        if execution.status == "running":
            execution.status = "pausing"
        execution.emit("control", state="pausing")
        return execution

    def resume(self, execution_id: str) -> Execution:
        execution = self._active(execution_id)
        execution.pause_requested = False
        execution.resume_event.set()
        execution.emit("control", state="resuming")
        return execution

    def steer(self, execution_id: str, message: str) -> Execution:
        execution = self._active(execution_id)
        text = message.strip()
        if not text:
            raise ValueError("steering message is required")
        execution.feedback.append(text)
        execution.emit("operator", action="steer_queued", text=text)
        return execution

    def cancel(self, execution_id: str) -> Execution:
        execution = self._active(execution_id)
        execution.cancel_requested = True
        execution.pause_requested = False
        execution.resume_event.set()
        execution.emit("control", state="cancelling")
        if execution.task is not None and not execution.task.done():
            execution.task.cancel()
        return execution

    async def events_after(
        self,
        execution_id: str,
        after: int = 0,
        *,
        wait: bool = False,
        timeout: float = 15.0,
    ) -> tuple[list[ExecutionEvent], bool]:
        execution = self.executions.get(execution_id)
        if execution is None:
            raise KeyError(execution_id)

        def current() -> list[ExecutionEvent]:
            return [event for event in execution.events if event.sequence > after]

        events = current()
        if not events and wait and execution.status not in TERMINAL_STATES:
            with contextlib.suppress(asyncio.TimeoutError):
                async with execution.condition:
                    await asyncio.wait_for(execution.condition.wait(), timeout=max(0.1, timeout))
            events = current()
        return events, execution.status in TERMINAL_STATES

    def _active(self, execution_id: str) -> Execution:
        execution = self.executions.get(execution_id)
        if execution is None:
            raise KeyError(execution_id)
        if execution.status in TERMINAL_STATES:
            raise RuntimeError(f"execution is already {execution.status}")
        return execution
