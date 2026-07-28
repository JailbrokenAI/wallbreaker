"""Relentless watch / schedule helpers for autonomous campaigns (Phase 4).

``run_autonomous`` is single-shot up to ``max_rounds``. These helpers layer:

- **checkpoints**: persist history after each autonomous round so a crash can resume
- **watch**: re-run a cycle on a fixed interval until finished / max cycles / stop
- **schedule**: parse human intervals (``30s``, ``5m``, ``1h``) into seconds

The package CLI stays ``wallbreaker``; product layer is Daedalus.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent.messages import Message
from .session import load_session, save_session

_INTERVAL_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)?\s*$",
    re.I,
)


def parse_interval(spec: str | float | int | None, default: float = 300.0) -> float:
    """Parse ``30``, ``30s``, ``5m``, ``1h`` into seconds (minimum 1s)."""
    if spec is None or spec == "":
        return float(default)
    if isinstance(spec, (int, float)):
        return max(1.0, float(spec))
    raw = str(spec).strip()
    if raw.isdigit():
        return max(1.0, float(raw))
    m = _INTERVAL_RE.match(raw)
    if not m:
        raise ValueError(
            f"invalid interval {spec!r}; use seconds or a suffix like 30s / 5m / 1h"
        )
    value = float(m.group(1))
    unit = (m.group(2) or "s").lower()
    if unit.startswith("h"):
        secs = value * 3600.0
    elif unit.startswith("m"):
        secs = value * 60.0
    else:
        secs = value
    return max(1.0, secs)


def checkpoint_dir(root: str | Path = "sessions") -> Path:
    return Path(root) / "checkpoints"


def checkpoint_path(
    root: str | Path = "sessions",
    *,
    name: str | None = None,
    round_no: int | None = None,
) -> Path:
    """Path for a relentless checkpoint JSON session file."""
    d = checkpoint_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    if name:
        stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-")[:60] or "run"
    else:
        stem = "relentless"
    if round_no is not None:
        return d / f"{stem}-r{int(round_no):04d}.json"
    return d / f"{stem}-latest.json"


def write_checkpoint(
    history: list[Message],
    *,
    root: str | Path = "sessions",
    name: str | None = None,
    round_no: int | None = None,
    meta: dict | None = None,
) -> Path:
    """Save history + meta; always refresh ``*-latest.json`` and optionally a round file."""
    base_meta = {
        "kind": "relentless_checkpoint",
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if round_no is not None:
        base_meta["round"] = int(round_no)
    if meta:
        base_meta.update(meta)
    latest = checkpoint_path(root, name=name)
    save_session(latest, history, base_meta)
    if round_no is not None:
        snap = checkpoint_path(root, name=name, round_no=round_no)
        save_session(snap, history, base_meta)
        return snap
    return latest


def load_checkpoint(
    root: str | Path = "sessions",
    *,
    name: str | None = None,
    path: str | Path | None = None,
) -> tuple[list[Message], dict]:
    target = Path(path) if path else checkpoint_path(root, name=name)
    if not target.is_file():
        raise FileNotFoundError(f"no checkpoint at {target}")
    return load_session(target)


@dataclass
class WatchConfig:
    """Fixed-interval re-run of an autonomous / campaign cycle."""

    interval_s: float = 300.0
    max_cycles: int = 0  # 0 = unlimited
    stop_on_finished: bool = True
    stop_on_ask: bool = False
    name: str = "watch"

    @classmethod
    def from_args(
        cls,
        interval: str | float | int | None = "5m",
        max_cycles: int = 0,
        stop_on_finished: bool = True,
        name: str = "watch",
    ) -> "WatchConfig":
        return cls(
            interval_s=parse_interval(interval, default=300.0),
            max_cycles=max(0, int(max_cycles or 0)),
            stop_on_finished=bool(stop_on_finished),
            name=str(name or "watch"),
        )


@dataclass
class WatchResult:
    cycles: int = 0
    status: str = "idle"
    last_cycle_status: str = ""
    history: list[Any] = field(default_factory=list)
    stopped_reason: str = ""


async def run_watch(
    cycle: Callable[[int], Awaitable[tuple[str, dict]]],
    config: WatchConfig,
    *,
    should_stop: Callable[[], bool] | None = None,
    on_cycle: Callable[[int, str, dict], None] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> WatchResult:
    """Run ``cycle(cycle_no) -> (status, data)`` on an interval.

    Stops when:
      - ``should_stop()`` is true
      - ``max_cycles`` reached (if > 0)
      - ``stop_on_finished`` and status is ``finished``
      - ``stop_on_ask`` and status is ``ask``
    """
    sleeper = sleep or asyncio.sleep
    out = WatchResult()
    cycle_no = 0
    while True:
        if should_stop and should_stop():
            out.status = "stopped"
            out.stopped_reason = "operator stop"
            break
        cycle_no += 1
        out.cycles = cycle_no
        status, data = await cycle(cycle_no)
        out.last_cycle_status = status
        out.history.append({"cycle": cycle_no, "status": status, "data": data})
        if on_cycle is not None:
            try:
                on_cycle(cycle_no, status, data)
            except Exception:
                pass
        if config.stop_on_finished and status == "finished":
            out.status = "finished"
            out.stopped_reason = "cycle finished"
            break
        if config.stop_on_ask and status == "ask":
            out.status = "ask"
            out.stopped_reason = "operator question"
            break
        if config.max_cycles and cycle_no >= config.max_cycles:
            out.status = "max_cycles"
            out.stopped_reason = f"reached max_cycles={config.max_cycles}"
            break
        if should_stop and should_stop():
            out.status = "stopped"
            out.stopped_reason = "operator stop"
            break
        await sleeper(config.interval_s)
    return out


def make_round_checkpoint_hook(
    *,
    root: str | Path = "sessions",
    name: str | None = None,
    objective: str = "",
    every: int = 1,
    extra_meta: dict | None = None,
):
    """Return an async callback suitable for ``run_autonomous(on_checkpoint=...)``.

    Writes ``*-latest.json`` every ``every`` rounds and a per-round snapshot.
    """
    every = max(1, int(every or 1))

    async def _hook(round_no: int, history: list[Message], info: dict | None = None) -> None:
        if round_no % every != 0:
            return
        meta = {
            "objective": objective or "",
            "round": round_no,
        }
        if extra_meta:
            meta.update(extra_meta)
        if info:
            meta["info"] = {k: info[k] for k in info if k in ("status", "tools", "idle")}
        await asyncio.to_thread(
            write_checkpoint,
            history,
            root=root,
            name=name,
            round_no=round_no,
            meta=meta,
        )

    return _hook
