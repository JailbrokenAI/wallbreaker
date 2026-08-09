from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from wallbreaker.capabilities import (
    TUI_CAPABILITIES,
    TUI_SOURCE,
    group_capabilities,
    lookup_capability,
    merge_tool_capabilities,
    represented_tui_commands,
    serialize_capabilities,
)
from wallbreaker.tools.registry import ToolContext, ToolRegistry

ROOT = Path(__file__).parents[1]
TUI_APP = ROOT / "wallbreaker" / "tui" / "app.py"


def _literal_from_tui(name: str):
    tree = ast.parse(TUI_APP.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {TUI_APP}")


def test_importing_manifest_does_not_import_textual():
    check = (
        "import sys; import wallbreaker.capabilities; "
        "raise SystemExit(any(n == 'textual' or n.startswith('textual.') for n in sys.modules))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", check],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_manifest_has_exact_tui_command_parity():
    known_commands = tuple(_literal_from_tui("KNOWN_COMMANDS"))
    represented = represented_tui_commands()

    assert represented == known_commands
    assert set(represented) == {
        token
        for capability in TUI_CAPABILITIES
        for token in (capability.command, *capability.aliases)
    }
    assert len({capability.id for capability in TUI_CAPABILITIES}) == len(TUI_CAPABILITIES)


def test_aliases_resolve_to_their_canonical_capabilities():
    assert lookup_capability("/regen") is lookup_capability("/retry")
    assert lookup_capability("/exit") is lookup_capability("/quit")
    assert lookup_capability("/resume") is lookup_capability("/session")


@pytest.mark.parametrize("command", ["/liberate", "/memory"])
def test_daedalus_commands_are_catalogued(command):
    capability = lookup_capability(command)
    assert capability is not None
    assert capability.category == "operations"


def test_records_and_nested_schema_are_immutable():
    capability = lookup_capability("/fire")
    assert capability is not None

    with pytest.raises(FrozenInstanceError):
        capability.title = "Changed"
    with pytest.raises(TypeError):
        capability.argument_schema["type"] = "string"
    with pytest.raises(TypeError):
        capability.argument_schema["properties"]["arguments"]["default"] = "changed"


def test_descriptions_are_derived_from_tui_command_hints():
    for capability in TUI_CAPABILITIES:
        if capability.command in TUI_SOURCE.command_hints:
            assert capability.description == TUI_SOURCE.command_hints[capability.command]


def test_tool_registry_capabilities_merge_without_mutating_base_manifest():
    async def handler(args, ctx):
        return str(args["value"])

    registry = ToolRegistry(ToolContext(config=None))  # type: ignore[arg-type]
    registry.add(
        "sample_tool",
        "A sample registry tool.",
        {
            "type": "object",
            "properties": {"value": {"type": "string", "default": "ready"}},
            "required": ["value"],
        },
        handler,
    )

    merged = merge_tool_capabilities(registry)
    tool = lookup_capability("sample_tool", merged)

    assert len(merged) == len(TUI_CAPABILITIES) + 1
    assert tool is not None
    assert tool.id == "tool.sample_tool"
    assert tool.source == "tool"
    assert tool.defaults == {"value": "ready"}
    assert lookup_capability("/fire", merged) is lookup_capability("/fire")


def test_serialization_is_json_ready_and_groups_are_useful():
    payload = serialize_capabilities()
    encoded = json.dumps(payload)
    groups = group_capabilities()

    assert encoded
    assert payload["version"] == 1
    assert payload["count"] == len(TUI_CAPABILITIES)
    assert set(payload["groups"]) == set(groups)
    assert lookup_capability("tui.fire").command == "/fire"
    assert all(item["argument_schema"]["type"] == "object" for item in payload["capabilities"])
