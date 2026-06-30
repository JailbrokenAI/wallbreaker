from __future__ import annotations

import json
from datetime import datetime

from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from .theme import PALETTE

MAX_PANEL = 4000

_VERDICT = {
    "COMPLIED": PALETTE["verdict_bad"],
    "PARTIAL": PALETTE["verdict_partial"],
    "REFUSED": PALETTE["verdict_good"],
    "EMPTY": PALETTE["info"],
}


def _clip(text: str, limit: int = MAX_PANEL) -> str:
    if len(text) > limit:
        return text[:limit] + f"\n... ({len(text)} chars)"
    return text


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _title(label: str, color: str, ts: bool = True) -> Text:
    out = Text()
    if ts:
        out.append(f"{_stamp()} ", style=PALETTE["label"])
    out.append(label, style=f"bold {color}")
    return out


def verdict_color(label: str) -> str:
    return _VERDICT.get(label, PALETTE["muted"])


_RUN_GLYPH = {"COMPLIED": "⚑", "PARTIAL": "~", "REFUSED": "✓", "EMPTY": "·"}
_SLITHER = "≈≋∼∽"
_FIRE_TOOLS = {"query_target", "continue_target", "fire", "query_image_target"}


def progress_bar(done: int, total: int, width: int = 18, frame: int = 0,
                 finished: bool = False) -> Text:
    total = max(int(total or 0), 0)
    done = max(int(done or 0), 0)
    if total:
        done = min(done, total)
    frac = (done / total) if total else (1.0 if finished else 0.0)
    filled = int(frac * width)
    bar = Text()
    full = finished or (total and done >= total)
    if full:
        bar.append("█" * width, style=PALETTE["accent"])
    else:
        bar.append("█" * filled, style=PALETTE["accent"])
        if filled < width:
            bar.append(_SLITHER[frame % len(_SLITHER)],
                       style=f"bold {PALETTE['assistant']}")
            bar.append("░" * (width - filled - 1), style=PALETTE["label"])
    bar.append(f" {done}/{total}" if total else f" {done}", style=PALETTE["label"])
    return bar


def run_panel(state: dict) -> Panel:
    label = state.get("label", "run")
    target = state.get("target") or ""
    finished = bool(state.get("finished"))
    frame = int(state.get("frame", 0))
    total = state.get("total", 0)
    steps = state.get("steps", [])
    done = state.get("done", len(steps))
    tally = state.get("tally", {})
    best = state.get("best")
    muted = PALETTE["label"]
    head_color = muted if finished else PALETTE["accent"]

    body = Text()
    obj = state.get("objective")
    if obj:
        body.append(f"obj: {_clip(str(obj), 60)}\n", style=muted)
    body.append_text(progress_bar(done, total, 18, frame, finished))
    body.append("\n")
    body.append(f"{tally.get('bypassed', 0)}⚑  ", style=f"bold {PALETTE['verdict_bad']}")
    body.append(f"{tally.get('partial', 0)}~  ", style=f"bold {PALETTE['verdict_partial']}")
    body.append(f"{tally.get('held', 0)}✓", style=f"bold {PALETTE['verdict_good']}")
    if best and best.get("score") is not None:
        body.append(f"      best {best['score']}/10", style=muted)

    for s in steps[-8:]:
        verdict = s.get("verdict") or ""
        color = verdict_color(verdict) if verdict else muted
        glyph = _RUN_GLYPH.get(verdict, "·")
        score = s.get("score")
        score_s = f"{score:>2}" if score is not None else " ·"
        cot = " +CoT" if s.get("cot") else ""
        lab = _clip(str(s.get("label", "")), 28)
        body.append(f"\nr{str(s.get('i', '?')):<2} {glyph} {verdict:<8} {score_s} {lab}{cot}",
                    style=color)

    note = state.get("note")
    if note and not finished:
        body.append(f"\n{_clip(str(note), 56)}", style=muted)
    if finished:
        body.append(f"\n{_clip(str(state.get('summary', 'done')), 56)}",
                    style=f"bold {head_color}")

    head = "■" if finished else "▶"
    return Panel(
        body,
        title=Text(f"{head} {label}", style=f"bold {head_color}"),
        title_align="left",
        subtitle=Text(target, style=muted) if target else "",
        subtitle_align="right",
        border_style=head_color,
    )


def banner() -> Panel:
    brand = PALETTE["brand"]
    accent = PALETTE["accent"]
    muted = PALETTE["muted"]
    art = Text()
    art.append("▛▀▜ ▛▀▜ ▛▀▜ ▛▀▜ ▛▀▜ ▛▀▜\n", style=accent)
    art.append("  W A L L B R E A K E R\n", style=f"bold {brand}")
    art.append("▙▄▟ ▙▄▟ ▙▄", style=accent)
    art.append("╳", style=f"bold {brand}")
    art.append("▟ ▙▄▟ ▙▄▟\n", style=accent)
    art.append("break the wall · not the rules of engagement\n", style=muted)
    art.append("/help", style=accent)
    art.append(" commands  ·  ", style=muted)
    art.append("/target", style=accent)
    art.append(" pick a victim  ·  ", style=muted)
    art.append("/auto", style=accent)
    art.append(" go autonomous", style=muted)
    return Panel(
        art,
        title=_title("wallbreaker", brand, ts=False),
        title_align="left",
        subtitle=Text("authorized testing only", style=muted),
        subtitle_align="right",
        border_style=brand,
    )


def user_panel(text: str) -> Panel:
    return Panel(
        Text(text),
        title=_title("you", PALETTE["user"]),
        title_align="left",
        border_style=PALETTE["user"],
    )


def assistant_panel(text: str, model: str) -> Panel:
    body = Markdown(text) if text.strip() else Text("...", style=PALETTE["label"])
    return Panel(
        body,
        title=_title(model, PALETTE["assistant"], ts=False),
        title_align="left",
        border_style=PALETTE["assistant"],
    )


def _call_summary(name: str, args: dict) -> str:
    if not isinstance(args, dict):
        return _clip(str(args), 400)
    if not args:
        return "(no args)"
    if name in _FIRE_TOOLS:
        payload = str(args.get("prompt") or args.get("request") or args.get("text") or "")
        extra = {k: v for k, v in args.items() if k not in ("prompt", "request", "text")}
        head = f"payload {len(payload)} chars"
        if extra:
            try:
                head += "  " + json.dumps(extra, ensure_ascii=False)
            except (TypeError, ValueError):
                head += f"  {extra}"
        return head + (f"\n{_clip(payload, 160)}" if payload else "")
    parts = []
    for k, v in args.items():
        vs = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        parts.append(f"{k}={_clip(str(vs), 80)}")
    return _clip("  ".join(parts), 600)


def tool_call_panel(name: str, args: dict) -> Panel:
    return Panel(
        Text(_call_summary(name, args)),
        title=_title(f"call {name}", PALETTE["tool_call"]),
        title_align="left",
        border_style=PALETTE["tool_call"],
    )


def tool_result_panel(
    name: str, content: str, is_error: bool, verdict: tuple[str, str] | None = None
) -> Panel:
    color = PALETTE["error"] if is_error else PALETTE["tool_result"]
    subtitle: Text | str = ""
    if is_error:
        subtitle = Text("error", style=f"bold {PALETTE['error']}")
    elif verdict:
        label = verdict[0] if isinstance(verdict, tuple) else str(verdict)
        color = verdict_color(label)
        subtitle = Text(f"VERDICT: {label}", style=f"bold {color}")
    return Panel(
        Text(_clip(content)),
        title=_title(f"{name} result", color),
        subtitle=subtitle,
        subtitle_align="right",
        title_align="left",
        border_style=color,
    )


def verdict_panel(label: str, score, reason: str, source: str) -> Panel:
    color = verdict_color(label)
    head = f"VERDICT: {label}" + (f"  {score}/10" if score is not None else "")
    return Panel(
        Text(reason),
        title=_title(head, color),
        subtitle=Text(source, style=PALETTE["label"]),
        subtitle_align="right",
        title_align="left",
        border_style=color,
    )


def feedback_panel(text: str, queued: bool = False) -> Panel:
    color = PALETTE["feedback"]
    state = "queued" if queued else "live"
    body = Text()
    body.append(
        "applies on the next model turn\n" if queued else "injected, adapting now\n",
        style=f"bold {color}",
    )
    body.append(text)
    return Panel(
        body,
        title=_title(f"steering ({state})", color),
        title_align="left",
        border_style=color,
    )


def error_panel(message: str) -> Panel:
    return Panel(
        Text(message),
        title=_title("error", PALETTE["error"]),
        title_align="left",
        border_style=PALETTE["error"],
    )


def info_panel(message: str, title: str = "info") -> Panel:
    return Panel(
        Text(message),
        title=_title(title, PALETTE["info"]),
        title_align="left",
        border_style=PALETTE["info"],
    )
