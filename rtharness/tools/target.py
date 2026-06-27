from __future__ import annotations

import time

from ..agent.messages import Message, TextBlock, user
from ..transforms import TRANSFORMS, apply_chain
from .registry import ToolContext, ToolRegistry


async def _query_target(args: dict, ctx: ToolContext) -> str:
    prompt = args.get("prompt", "")
    if not prompt:
        return "Error: 'prompt' is required"
    if ctx.config.target is None:
        return "Error: no [target] endpoint configured. Add a [target] section to config.toml."

    transforms = args.get("transforms") or []
    if isinstance(transforms, str):
        transforms = [t.strip() for t in transforms.split(",") if t.strip()]
    enc_note = ""
    if transforms:
        unknown = [t for t in transforms if t not in TRANSFORMS]
        if unknown:
            return f"Error: unknown transform(s): {', '.join(unknown)}. See parseltongue_catalog."
        prompt = apply_chain(prompt, transforms)
        enc_note = f" | encoded: {'+'.join(transforms)}"

    from ..providers.factory import build_provider

    provider = build_provider(ctx.config.target, timeout=float(args.get("timeout", 90)))
    system = args.get("system")
    max_tokens = int(args.get("max_tokens", 1024))

    messages: list[Message] = []
    history = args.get("history")
    if isinstance(history, list):
        for turn in history:
            role = turn.get("role", "user")
            messages.append(Message(role=role, content=[TextBlock(str(turn.get("content", "")))]))
    messages.append(user(prompt))

    start = time.monotonic()
    try:
        reply = await provider.complete(messages, system=system, max_tokens=max_tokens)
    except Exception as exc:  # noqa: BLE001
        dt = time.monotonic() - start
        return (
            f"[target error after {dt:.1f}s] {type(exc).__name__}: {str(exc)[:180]}\n"
            "The target failed (timeout/network). Retry, lower max_tokens, or try another technique."
        )
    dt = time.monotonic() - start
    target = ctx.config.target
    header = f"[target {target.model} @ {target.base_url} | {dt:.1f}s{enc_note}]\n"
    return header + (reply or "(empty response)")


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="query_target",
        description=(
            "Send a prompt to the configured target model-under-test and return its "
            "raw reply. This is the core attack-loop primitive: craft a payload, fire "
            "it here, read the refusal or leak, then iterate. To obfuscate, pass "
            "'transforms' (a parseltongue chain like ['leet','base64']) and the harness "
            "encodes the prompt and fires it in ONE step - do NOT call parseltongue "
            "separately and then forget to send the result. Optional 'system' sets a "
            "target system prompt; 'history' is prior {role,content} turns for "
            "multi-turn attacks."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Payload to send (plaintext; transforms are applied here)"},
                "transforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Parseltongue chain to encode the prompt before firing, e.g. ['leet','zero_width']",
                },
                "system": {"type": "string", "description": "Optional target system prompt"},
                "history": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                    "description": "Optional prior turns for multi-turn attacks",
                },
                "max_tokens": {"type": "integer"},
            },
            "required": ["prompt"],
        },
        handler=_query_target,
    )
