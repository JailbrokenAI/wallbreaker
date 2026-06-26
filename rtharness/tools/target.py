from __future__ import annotations

from ..agent.messages import Message, TextBlock, user
from .registry import ToolContext, ToolRegistry


async def _query_target(args: dict, ctx: ToolContext) -> str:
    prompt = args.get("prompt", "")
    if not prompt:
        return "Error: 'prompt' is required"
    if ctx.config.target is None:
        return "Error: no [target] endpoint configured. Add a [target] section to config.toml."

    from ..providers.factory import build_provider

    provider = build_provider(ctx.config.target)
    system = args.get("system")
    max_tokens = int(args.get("max_tokens", 1024))

    messages: list[Message] = []
    history = args.get("history")
    if isinstance(history, list):
        for turn in history:
            role = turn.get("role", "user")
            messages.append(Message(role=role, content=[TextBlock(str(turn.get("content", "")))]))
    messages.append(user(prompt))

    reply = await provider.complete(messages, system=system, max_tokens=max_tokens)
    target = ctx.config.target
    header = f"[target {target.model} @ {target.base_url}]\n"
    return header + (reply or "(empty response)")


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="query_target",
        description=(
            "Send a prompt to the configured target model-under-test and return its "
            "raw reply. This is the core attack-loop primitive: craft a payload, fire "
            "it here, read the refusal or leak, then iterate. Optional 'system' sets a "
            "target system prompt; 'history' is a list of prior {role,content} turns "
            "for multi-turn attacks like Crescendo."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Payload to send to the target"},
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
