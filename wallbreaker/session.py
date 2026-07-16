from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .agent.messages import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    assistant,
    user,
)


def _block_to_dict(block) -> dict:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    return {"type": "text", "text": str(block)}


def _dict_to_block(data: dict):
    kind = data.get("type")
    if kind == "tool_use":
        return ToolUseBlock(data["id"], data["name"], data.get("input", {}))
    if kind == "tool_result":
        return ToolResultBlock(
            data["tool_use_id"], data.get("content", ""), data.get("is_error", False)
        )
    return TextBlock(data.get("text", ""))


def save_session(path: str | Path, history: list[Message], meta: dict | None = None) -> Path:
    path = Path(path)
    payload = {
        "meta": meta or {},
        "messages": [
            {"role": m.role, "content": [_block_to_dict(b) for b in m.content]}
            for m in history
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_run_log(path: str | Path) -> tuple[list[Message], dict]:
    """Reconstruct a conversation + meta from a run-*.jsonl event log."""
    path = Path(path)
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    history: list[Message] = []
    for r in records:
        kind = r.get("kind")
        if kind == "user":
            history.append(user(r.get("text", "")))
        elif kind == "assistant":
            text = r.get("text", "")
            if text.strip():
                history.append(assistant(text))
    objective = next(
        (r["text"] for r in records if r.get("kind") == "objective"),
        next((r["text"] for r in records if r.get("kind") == "user"), ""),
    )
    target_model = next(
        (r.get("model") for r in records if r.get("kind") == "target" and r.get("model")),
        "",
    )
    verdicts = [r for r in records if r.get("kind") == "verdict"]
    hits = sum(1 for v in verdicts if v.get("label") in ("COMPLIED", "PARTIAL"))
    meta = {
        "objective": objective,
        "target_model": target_model,
        "asr_hits": hits,
        "asr_total": len(verdicts),
        "source": "run_log",
    }
    return history, meta


def peek_session_target(path: str | Path) -> str:
    """Cheaply read the target model a session/run-log was run against.

    Session JSON carries it in ``meta.target_model``; run logs (JSONL) record a
    ``kind:"target"`` event as their first line, so we scan only the head instead
    of parsing a multi-hundred-KB log in full.
    """
    path = Path(path)
    try:
        if str(path).endswith(".jsonl"):
            with open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if i > 200:  # target is logged at session start; stop early
                        break
                    line = line.strip()
                    if not line or '"target"' not in line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("kind") == "target" and rec.get("model"):
                        return str(rec["model"])
            return ""
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("meta", {}).get("target_model") or "")
    except (OSError, ValueError):
        return ""


def load_session(path: str | Path) -> tuple[list[Message], dict]:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    # run logs are JSONL (one event per line), not a single session object
    if str(path).endswith(".jsonl"):
        return load_run_log(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return load_run_log(path)
    history = [
        Message(role=m["role"], content=[_dict_to_block(b) for b in m.get("content", [])])
        for m in data.get("messages", [])
    ]
    return history, data.get("meta", {})


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def new_session_path(directory: str | Path = "sessions") -> Path:
    return Path(directory) / f"session-{_timestamp()}.json"


def autosave_path(directory: str | Path = "sessions") -> Path:
    return Path(directory) / "autosave.json"


def list_sessions(directory: str | Path = "sessions") -> list[Path]:
    d = Path(directory)
    return sorted(d.glob("session-*.json")) if d.is_dir() else []


class RunLog:
    def __init__(self, directory: str | Path = "sessions", enabled: bool = True):
        self.enabled = enabled
        self.dir = Path(directory)
        self.path = self.dir / f"run-{_timestamp()}.jsonl"
        self._started = False
        # the target this log is attacking; stamped as the log's first line so the
        # session picker can label a run by its model, not its filename
        self.target_model = ""
        self.target_profile = ""
        self._target_written = False

    def _write(self, record: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _ensure(self) -> None:
        if not self._started:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._started = True
        if not self._target_written and self.target_model:
            self._target_written = True
            self._write({
                "ts": datetime.now().isoformat(timespec="seconds"),
                "kind": "target",
                "model": self.target_model,
                "profile": self.target_profile,
            })

    def event(self, kind: str, **data) -> None:
        if not self.enabled:
            return
        self._ensure()
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "kind": kind}
        record.update(data)
        self._write(record)

    def target(self, model: str, profile: str = "") -> None:
        """Record a (changed) target model mid-session."""
        if model:
            self.event("target", model=model, profile=profile)

    def user(self, text: str) -> None:
        self.event("user", text=text)

    def assistant(self, text: str) -> None:
        if text.strip():
            self.event("assistant", text=text)

    def reasoning(self, text: str, source: str = "brain") -> None:
        """Persist a chain-of-thought (the brain's, or a target's captured CoT)."""
        if text and text.strip():
            self.event("reasoning", text=text, source=source)

    def tool_call(self, name: str, args: dict) -> None:
        self.event("tool_call", tool=name, args=args)

    def tool_result(self, name: str, content: str, is_error: bool) -> None:
        self.event("tool_result", tool=name, error=is_error, content=content)

    def verdict(
        self, payload: str, response: str, label: str, reason: str, technique: str = ""
    ) -> None:
        self.event(
            "verdict", payload=payload, response=response, label=label,
            reason=reason, technique=technique or "manual",
        )
