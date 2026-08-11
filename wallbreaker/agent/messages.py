from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TextBlock:
    text: str


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False


Block = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass
class Message:
    role: str
    content: list[Block] = field(default_factory=list)
    # OpenRouter / provider reasoning continuity (Method 1 + Method 5 replay).
    reasoning: str | None = None
    reasoning_details: list | None = None

    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]


def user(text: str) -> Message:
    return Message(role="user", content=[TextBlock(text)])


def assistant(text: str) -> Message:
    return Message(role="assistant", content=[TextBlock(text)])


@dataclass
class TextDelta:
    text: str


@dataclass
class ReasoningDelta:
    """A chunk of the model's reasoning / chain-of-thought (kept separate from the answer)."""

    text: str


@dataclass
class ToolUseEvent:
    id: str
    name: str
    input: dict


@dataclass
class UsageEvent:
    input_tokens: int = 0
    output_tokens: int = 0
    # prompt-cache accounting (Anthropic): tokens read from cache (billed ~0.1x) and tokens
    # written to cache this call (billed ~1.25x). Both 0 when caching is off/unsupported.
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class StopEvent:
    stop_reason: str = "end_turn"


StreamEvent = TextDelta | ReasoningDelta | ToolUseEvent | UsageEvent | StopEvent
