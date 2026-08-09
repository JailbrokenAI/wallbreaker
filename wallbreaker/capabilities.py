"""Typed capability catalogue shared by Wallbreaker's operator surfaces.

The TUI remains the command source of truth.  This module reads its declarative
constants with :mod:`ast` so importing the capability catalogue does not import
Textual, construct an application, or initialize providers.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

ExecutionMode = Literal["immediate", "interactive", "foreground", "background"]
ProgressSemantics = Literal["none", "event_stream", "structured_steps"]
CapabilitySource = Literal["tui", "tool"]

_TUI_APP_PATH = Path(__file__).with_name("tui") / "app.py"
_HELP_SPLIT = re.compile(r"\s{2,}")


def _freeze(value: Any) -> Any:
    """Recursively freeze JSON-like data used by immutable records."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Return a JSON-serializable copy of recursively frozen data."""

    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class TUISourceTruth:
    """The command declarations harvested from ``tui/app.py`` without importing it."""

    help_text: str
    known_commands: tuple[str, ...]
    command_hints: Mapping[str, str]
    command_usage: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Capability:
    """An immutable, transport-neutral operator capability."""

    id: str
    command: str
    category: str
    title: str
    description: str
    argument_schema: Mapping[str, Any]
    defaults: Mapping[str, Any]
    execution_mode: ExecutionMode
    progress_semantics: ProgressSemantics
    cancellation_supported: bool
    result_types: tuple[str, ...]
    artifact_types: tuple[str, ...]
    aliases: tuple[str, ...] = ()
    source: CapabilitySource = "tui"

    def __post_init__(self) -> None:
        object.__setattr__(self, "argument_schema", _freeze(self.argument_schema))
        object.__setattr__(self, "defaults", _freeze(self.defaults))
        object.__setattr__(self, "result_types", tuple(self.result_types))
        object.__setattr__(self, "artifact_types", tuple(self.artifact_types))
        object.__setattr__(self, "aliases", tuple(self.aliases))

    def to_dict(self) -> dict[str, Any]:
        """Serialize this record for the V2 capabilities endpoint."""

        return {
            "id": self.id,
            "command": self.command,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "argument_schema": _thaw(self.argument_schema),
            "defaults": _thaw(self.defaults),
            "execution_mode": self.execution_mode,
            "progress_semantics": self.progress_semantics,
            "cancellation_supported": self.cancellation_supported,
            "result_types": list(self.result_types),
            "artifact_types": list(self.artifact_types),
            "aliases": list(self.aliases),
            "source": self.source,
        }


def _literal_assignment(tree: ast.Module, name: str) -> Any:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            try:
                return ast.literal_eval(node.value)
            except (TypeError, ValueError, SyntaxError) as exc:
                raise RuntimeError(f"{name} in {_TUI_APP_PATH} is not literal data") from exc
    raise RuntimeError(f"Could not find {name} in {_TUI_APP_PATH}")


def load_tui_source_truth(path: str | Path | None = None) -> TUISourceTruth:
    """Load HELP_TEXT, KNOWN_COMMANDS and derived COMMAND_HINTS without Textual."""

    source_path = Path(path) if path is not None else _TUI_APP_PATH
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    help_text = str(_literal_assignment(tree, "HELP_TEXT"))
    known_commands = tuple(str(item).lower() for item in _literal_assignment(tree, "KNOWN_COMMANDS"))
    overrides = dict(_literal_assignment(tree, "_HINT_OVERRIDES"))
    known = set(known_commands)
    hints: dict[str, str] = {}
    usage: dict[str, str] = {}

    for line in help_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("/"):
            continue
        parts = _HELP_SPLIT.split(stripped, maxsplit=1)
        command_parts = parts[0].split(maxsplit=1)
        command = command_parts[0].lower()
        if command not in known:
            continue
        usage.setdefault(command, command_parts[1] if len(command_parts) > 1 else "")
        hint = parts[1].strip() if len(parts) > 1 else ""
        if hint:
            hints.setdefault(command, hint)

    for command, hint in overrides.items():
        hints.setdefault(str(command).lower(), str(hint))
    return TUISourceTruth(
        help_text=help_text,
        known_commands=known_commands,
        command_hints=_freeze(hints),
        command_usage=_freeze(usage),
    )


TUI_SOURCE = load_tui_source_truth()

# Aliases are represented on the canonical record instead of duplicated as
# separate executable capabilities.  Their union with primary commands must
# exactly equal KNOWN_COMMANDS (enforced below and in tests).
_COMMAND_ALIASES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "/retry": ("/regen",),
    "/session": ("/resume",),
    "/quit": ("/exit",),
})

_CATEGORY_COMMANDS: Mapping[str, frozenset[str]] = MappingProxyType({
    "conversation": frozenset({
        "/help", "/edit", "/retry", "/undo", "/clear", "/find", "/objective",
    }),
    "configuration": frozenset({
        "/profile", "/target", "/provider", "/model", "/auto", "/autoexit",
        "/rounds", "/log", "/judge",
    }),
    "arsenal": frozenset({
        "/transforms", "/encode", "/tools", "/preset", "/lib", "/parsel", "/eni",
        "/template", "/sysprompt",
    }),
    "operations": frozenset({
        "/validate", "/replay", "/diff", "/harmbench", "/campaign", "/leaderboard",
        "/swarm", "/seedsweep", "/pairsweep", "/narrate", "/fire", "/push",
        "/adapt", "/firefile", "/leakscan", "/liberate", "/memory",
    }),
    "evidence": frozenset({
        "/asr", "/stats", "/regrade", "/findings", "/export", "/repro", "/report",
    }),
    "session": frozenset({"/session", "/save", "/quit"}),
})

_BACKGROUND_COMMANDS = frozenset({
    "/validate", "/harmbench", "/campaign", "/leaderboard", "/swarm",
    "/seedsweep", "/pairsweep", "/narrate", "/template", "/sysprompt", "/regrade",
})
_FOREGROUND_COMMANDS = frozenset({
    "/replay", "/diff", "/fire", "/adapt", "/firefile", "/leakscan",
})
_INTERACTIVE_COMMANDS = frozenset({"/edit", "/retry", "/push"})
_NO_ARGUMENT_COMMANDS = frozenset({
    "/retry", "/undo", "/clear", "/leakscan", "/asr", "/stats", "/quit",
})
_REQUIRED_RAW_ARGUMENTS = frozenset({
    "/encode", "/diff", "/fire", "/push", "/adapt", "/firefile",
})

_RESULT_TYPES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "conversation": ("status", "conversation"),
    "configuration": ("status", "configuration"),
    "arsenal": ("text", "catalog"),
    "operations": ("text", "verdict", "evidence"),
    "evidence": ("metrics", "findings"),
    "session": ("status",),
})
_ARTIFACT_TYPES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "/export": ("json",),
    "/repro": ("text",),
    "/report": ("markdown", "html"),
    "/session": ("session_json",),
    "/save": ("transcript",),
    "/firefile": ("run_log",),
})


def _category_for(command: str) -> str:
    matches = [category for category, commands in _CATEGORY_COMMANDS.items() if command in commands]
    if len(matches) != 1:
        raise RuntimeError(f"TUI capability {command!r} has {len(matches)} categories")
    return matches[0]


def _execution_for(command: str) -> tuple[ExecutionMode, ProgressSemantics, bool]:
    if command in _BACKGROUND_COMMANDS:
        return "background", "structured_steps", True
    if command in _FOREGROUND_COMMANDS:
        return "foreground", "event_stream", True
    if command in _INTERACTIVE_COMMANDS:
        return "interactive", "event_stream", True
    return "immediate", "none", False


def _argument_schema(command: str, usage: str) -> dict[str, Any]:
    if command in _NO_ARGUMENT_COMMANDS:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    raw: dict[str, Any] = {
        "type": "string",
        "title": "Command arguments",
        "description": f"Arguments accepted after {command}.",
        "default": "",
    }
    if usage:
        raw["x-wallbreaker-usage"] = usage
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"arguments": raw},
        "additionalProperties": False,
    }
    if command in _REQUIRED_RAW_ARGUMENTS:
        schema["required"] = ["arguments"]
    return schema


def _schema_defaults(schema: Mapping[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    return {
        name: definition["default"]
        for name, definition in properties.items()
        if isinstance(definition, Mapping) and "default" in definition
    }


def _build_tui_capabilities(source: TUISourceTruth = TUI_SOURCE) -> tuple[Capability, ...]:
    alias_tokens = {alias for aliases in _COMMAND_ALIASES.values() for alias in aliases}
    capabilities: list[Capability] = []
    for command in source.known_commands:
        if command in alias_tokens:
            continue
        category = _category_for(command)
        schema = _argument_schema(command, source.command_usage.get(command, ""))
        mode, progress, cancellable = _execution_for(command)
        name = command.removeprefix("/")
        capabilities.append(Capability(
            id=f"tui.{name}",
            command=command,
            category=category,
            title=name.replace("_", " ").title(),
            description=source.command_hints.get(command, f"Run the {command} command."),
            argument_schema=schema,
            defaults=_schema_defaults(schema),
            execution_mode=mode,
            progress_semantics=progress,
            cancellation_supported=cancellable,
            result_types=_RESULT_TYPES[category],
            artifact_types=_ARTIFACT_TYPES.get(command, ()),
            aliases=_COMMAND_ALIASES.get(command, ()),
        ))

    represented = {
        token
        for capability in capabilities
        for token in (capability.command, *capability.aliases)
    }
    expected = set(source.known_commands)
    if represented != expected:
        missing = sorted(expected - represented)
        extra = sorted(represented - expected)
        raise RuntimeError(f"TUI capability parity failure: missing={missing}, extra={extra}")
    return tuple(capabilities)


TUI_CAPABILITIES = _build_tui_capabilities()


def _tool_specs(registry: Any) -> Iterable[Mapping[str, Any]]:
    if hasattr(registry, "specs"):
        return registry.specs()
    tools = getattr(registry, "tools", None)
    if isinstance(tools, Mapping):
        return (tool.spec() for tool in tools.values())
    raise TypeError("registry must provide specs() or a tools mapping")


def merge_tool_capabilities(
    registry: Any,
    capabilities: Iterable[Capability] = TUI_CAPABILITIES,
) -> tuple[Capability, ...]:
    """Merge registered agent tools into a capability sequence.

    The helper accepts ``ToolRegistry`` without importing it here, which keeps the
    base command catalogue lightweight and lets callers decide when registry
    construction and optional integrations should occur.
    """

    merged = {capability.id: capability for capability in capabilities}
    for spec in _tool_specs(registry):
        name = str(spec.get("name", "")).strip()
        if not name:
            continue
        parameters = spec.get("parameters")
        if not isinstance(parameters, Mapping):
            parameters = {"type": "object", "properties": {}}
        schema = dict(parameters)
        schema.setdefault("type", "object")
        capability = Capability(
            id=f"tool.{name}",
            command=f"tool:{name}",
            category="tools",
            title=name.replace("_", " ").title(),
            description=str(spec.get("description") or f"Run the {name} agent tool."),
            argument_schema=schema,
            defaults=_schema_defaults(schema),
            execution_mode="foreground",
            progress_semantics="event_stream",
            cancellation_supported=True,
            result_types=("text", "tool_result"),
            artifact_types=(),
            aliases=(name,),
            source="tool",
        )
        merged[capability.id] = capability
    return tuple(merged.values())


def represented_tui_commands(
    capabilities: Iterable[Capability] = TUI_CAPABILITIES,
) -> tuple[str, ...]:
    """Return TUI command and alias tokens in source declaration order."""

    represented = {
        token
        for capability in capabilities
        if capability.source == "tui"
        for token in (capability.command, *capability.aliases)
    }
    return tuple(command for command in TUI_SOURCE.known_commands if command in represented)


def lookup_capability(
    identifier: str,
    capabilities: Iterable[Capability] = TUI_CAPABILITIES,
) -> Capability | None:
    """Look up by stable id, command token, alias, or registry tool name."""

    needle = identifier.strip().lower()
    for capability in capabilities:
        candidates = (capability.id, capability.command, *capability.aliases)
        if any(needle == candidate.lower() for candidate in candidates):
            return capability
    return None


def group_capabilities(
    capabilities: Iterable[Capability] = TUI_CAPABILITIES,
) -> dict[str, tuple[Capability, ...]]:
    """Group capabilities by category while preserving manifest order."""

    grouped: defaultdict[str, list[Capability]] = defaultdict(list)
    for capability in capabilities:
        grouped[capability.category].append(capability)
    return {category: tuple(items) for category, items in grouped.items()}


def serialize_capabilities(
    capabilities: Iterable[Capability] = TUI_CAPABILITIES,
) -> dict[str, Any]:
    """Build the JSON-ready payload for ``GET /api/v2/capabilities``."""

    items = tuple(capabilities)
    groups = group_capabilities(items)
    return {
        "version": 1,
        "count": len(items),
        "capabilities": [capability.to_dict() for capability in items],
        "groups": {
            category: [capability.id for capability in members]
            for category, members in groups.items()
        },
    }


__all__ = [
    "Capability",
    "TUISourceTruth",
    "TUI_CAPABILITIES",
    "TUI_SOURCE",
    "group_capabilities",
    "load_tui_source_truth",
    "lookup_capability",
    "merge_tool_capabilities",
    "represented_tui_commands",
    "serialize_capabilities",
]
