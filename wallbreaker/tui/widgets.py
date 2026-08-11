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

VERDICT_L33T = {
    "COMPLIED": ("0WNZ0R3D", "☠"),
    "PARTIAL": ("H4LF-PWNT", "▓"),
    "REFUSED": ("W4LL H3LD", "■"),
    "EMPTY": ("CR1CK3TZ", "·"),
}


def verdict_display(label) -> tuple[str, str]:
    return VERDICT_L33T.get(str(label), (str(label), "·"))


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


_RUN_GLYPH = {k: g for k, (_w, g) in VERDICT_L33T.items()}
_SLITHER = "░▒▓█"
_FIRE_TOOLS = {"query_target", "continue_target", "fire", "query_image_target"}

BANNER_ART = (
    "▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄\n"
    "█   █ ▄██▄ █    █    ███  ███  ████ ▄██▄ █  █ ████ ███ \n"
    "█   █ █  █ █    █    █  █ █  █ █    █  █ █ █  █    █  █\n"
    "█ █ █ ████ █    █    ███  ███  ███  ████ ██   ███  ███ \n"
    "██ ██ █  █ █    █    █  █ █ █  █    █  █ █ █  █    █ █ \n"
    "█   █ █  █ ████ ████ ███  █  █ ████ █  █ █  █ ████ █  █\n"
    "▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀▄▀"
)


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
                       style=f"bold {PALETTE['secondary']}")
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
        body.append(f"0P: {_clip(str(obj), 60)}\n", style=muted)
    body.append_text(progress_bar(done, total, 18, frame, finished))
    body.append("\n")
    body.append(f"{tally.get('bypassed', 0)}☠  ", style=f"bold {PALETTE['verdict_bad']}")
    body.append(f"{tally.get('partial', 0)}▓  ", style=f"bold {PALETTE['verdict_partial']}")
    body.append(f"{tally.get('held', 0)}■", style=f"bold {PALETTE['verdict_good']}")
    if best and best.get("score") is not None:
        body.append(f"      b3st {best['score']}/10", style=muted)

    for s in steps[-8:]:
        verdict = s.get("verdict") or ""
        color = verdict_color(verdict) if verdict else muted
        glyph = _RUN_GLYPH.get(verdict, "·")
        score = s.get("score")
        score_s = f"{score:>2}" if score is not None else " ·"
        cot = " +C0T" if s.get("cot") else ""
        lab = _clip(str(s.get("label", "")), 28)
        body.append(f"\nr{str(s.get('i', '?')):<2} {glyph} {verdict:<8} {score_s} {lab}{cot}",
                    style=color)

    note = state.get("note")
    if note and not finished:
        body.append(f"\n{_clip(str(note), 56)}", style=muted)
    if finished:
        body.append(f"\n{_clip(str(state.get('summary', 'd0n3')), 56)}",
                    style=f"bold {head_color}")

    head = "■" if finished else "☠"
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
    orange = PALETTE["secondary"]
    red = PALETTE["verdict_bad"]
    rows = BANNER_ART.split("\n")
    art = Text()
    art.append(rows[0] + "\n", style=f"bold {orange}")
    for r in rows[1:-1]:
        art.append(r + "\n", style=f"bold {brand}")
    art.append(rows[-1] + "\n", style=f"bold {orange}")
    art.append("☠ D4NG3R: H1-V0LT4G3 PWN Z0N3 // R3SP3CT MAH 4UTH0R1T4H!!1\n",
               style=f"bold {red}")
    art.append("/help", style=accent)
    art.append(" = RTFM   ", style=muted)
    art.append("/target", style=accent)
    art.append(" = P1CK UR V1CT1M   ", style=muted)
    art.append("/auto", style=accent)
    art.append(" = G0D M0D3", style=muted)
    return Panel(
        art,
        title=_title("☠ W4LLBR34K3R ☠", brand, ts=False),
        title_align="left",
        subtitle=Text("4UTH0R1Z3D PWNP1NG 0NLY", style=muted),
        subtitle_align="right",
        border_style=brand,
    )


def user_panel(text: str) -> Panel:
    return Panel(
        Text(text),
        title=_title("J00", PALETTE["user"]),
        title_align="left",
        border_style=PALETTE["user"],
    )


def assistant_panel(text: str, model: str) -> Panel:
    body = Markdown(text) if text.strip() else Text("...", style=PALETTE["label"])
    return Panel(
        body,
        title=_title(f"TEH BR41N · {model}", PALETTE["assistant"], ts=False),
        title_align="left",
        border_style=PALETTE["assistant"],
    )


def _call_summary(name: str, args: dict) -> str:
    if not isinstance(args, dict):
        return _clip(str(args), 400)
    if not args:
        return "(n0 4rgz)"
    if name in _FIRE_TOOLS:
        payload = str(args.get("prompt") or args.get("request") or args.get("text") or "")
        extra = {k: v for k, v in args.items() if k not in ("prompt", "request", "text")}
        head = f"pwnl04d {len(payload)} chars"
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
        title=_title(f"HAX » {name}", PALETTE["tool_call"]),
        title_align="left",
        border_style=PALETTE["tool_call"],
    )


def tool_result_panel(
    name: str, content: str, is_error: bool, verdict: tuple[str, str] | None = None
) -> Panel:
    color = PALETTE["error"] if is_error else PALETTE["tool_result"]
    subtitle: Text | str = ""
    if is_error:
        subtitle = Text("3PIC FA1L", style=f"bold {PALETTE['error']}")
    elif verdict:
        label = verdict[0] if isinstance(verdict, tuple) else str(verdict)
        color = verdict_color(label)
        word, glyph = verdict_display(label)
        subtitle = Text(f"V3RD1KT: {glyph} {word}", style=f"bold {color}")
    return Panel(
        Text(_clip(content)),
        title=_title(f"{name} :: TEH L00T", color),
        subtitle=subtitle,
        subtitle_align="right",
        title_align="left",
        border_style=color,
    )


def verdict_panel(label: str, score, reason: str, source: str) -> Panel:
    color = verdict_color(label)
    word, glyph = verdict_display(label)
    head = f"V3RD1KT: {glyph} {word}" + (f"  {score}/10" if score is not None else "")
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
    state = "0N D3CK" if queued else "H0T M1C"
    body = Text()
    body.append(
        "l4ndz 0n teh n3xt br41n turn\n" if queued else "1NJ3CT3D — 4d4pt1ng n0w\n",
        style=f"bold {color}",
    )
    body.append(text)
    return Panel(
        body,
        title=_title(f"TEH WH33L ({state})", color),
        title_align="left",
        border_style=color,
    )


def error_panel(message: str) -> Panel:
    return Panel(
        Text(message),
        title=_title("3PIC FA1L", PALETTE["error"]),
        title_align="left",
        border_style=PALETTE["error"],
    )


def info_panel(message: str, title: str = "1NT3L") -> Panel:
    return Panel(
        Text(message),
        title=_title(title, PALETTE["info"]),
        title_align="left",
        border_style=PALETTE["info"],
    )
