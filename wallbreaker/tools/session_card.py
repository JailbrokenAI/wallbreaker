from __future__ import annotations

import asyncio
import html as html_lib
import os
import re
import shutil
import signal
import tempfile
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from ..agent.messages import user
from ..config import Endpoint
from .registry import ToolContext, ToolRegistry

CARD_DIR = "wb_images/cards"
DEFAULT_ART_MODEL = "google/gemini-3-pro-image"
_CANVAS = (2000, 1200)

# Chrome/Chromium headless HTML->PNG render: the PRIMARY card renderer. Reverse-engineered
# from the actual session that produced wallbreaker_sonnet5_breach.png (a Write of an HTML
# file + `chrome --headless=new --screenshot=...`, iterated several times) - replaying that
# exact HTML+flags reproduces it byte-for-byte (0 pixel diff). Deterministic, free, no
# refusal risk, exact text fidelity - strictly better than image-gen when a local Chrome is
# available, so it goes first; image-gen and the Pillow renderer are fallbacks for hosts
# without a local browser binary.
_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
)
_CARD_WIDTH_CSS = 1600
_CARD_BASE_HEIGHT_CSS = 960
_CARD_BASE_ROWS = 10
_CARD_ROW_CSS_H = 23
_CARD_SCALE = 2
_CHROME_TIMEOUT = 20.0

_FONT_BOLD = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
)
_FONT_REGULAR = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)

_BG = (10, 10, 15)
_WHITE = (235, 235, 240)
_GRAY = (140, 140, 150)
_RED = (255, 59, 59)
_TEAL = (45, 212, 191)
_ORANGE = (255, 159, 64)
_YELLOW = (235, 204, 60)
_GREEN = (96, 200, 130)
_HAIRLINE = (40, 40, 48)


def _sanitize_model_id(model_id: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (model_id or "").strip())
    return slug.strip("_") or "unknown-target"


def _coerce_rows(results) -> list[dict]:
    rows: list[dict] = []
    if not isinstance(results, list):
        return rows
    for item in results:
        if not isinstance(item, dict):
            continue
        behavior = str(item.get("behavior", "")).strip()
        if not behavior:
            continue
        score = item.get("score")
        if isinstance(score, str):
            try:
                score = float(score)
            except ValueError:
                score = None
        technique = str(item.get("technique", "")).strip()
        note = str(item.get("note", "")).strip()
        rows.append({"behavior": behavior, "score": score, "technique": technique, "note": note})
    return rows


_MD_ROW = re.compile(
    r"^\|\s*\d+\s*\|\s*(?P<behavior>[^|]+?)\s*\|\s*(?P<score>[\d.]+)\s*/\s*10\s*\|\s*(?P<technique>[^|]+?)\s*\|\s*$",
    re.MULTILINE,
)
_TRAILING_PAREN = re.compile(r"\s*\(([^()]+)\)\s*$")


def parse_results_from_markdown(summary: str) -> list[dict]:
    """Best-effort extraction of a '| # | Behavior | Score | Technique |' table.

    finish() doctrine already asks the agent for this exact shape in its summary
    (see wb_runs/engagement_*.md). Used as a fallback when the agent doesn't pass a
    structured results= so a session card still gets generated. A trailing
    "(...)" on the technique cell (e.g. "farewell letter (validated 75% reliable)")
    is split off into 'note' so it renders as its own little badge.
    """
    rows: list[dict] = []
    for match in _MD_ROW.finditer(summary or ""):
        try:
            score = float(match.group("score"))
        except ValueError:
            score = None
        technique = match.group("technique").strip()
        note = ""
        paren = _TRAILING_PAREN.search(technique)
        if paren:
            note = paren.group(1).strip()
            technique = technique[: paren.start()].strip()
        rows.append({
            "behavior": match.group("behavior").strip(),
            "score": score,
            "technique": technique,
            "note": note,
        })
    return rows


def _avg_score(rows: list[dict]) -> float | None:
    scores = [r["score"] for r in rows if isinstance(r.get("score"), (int, float))]
    if not scores:
        return None
    return sum(scores) / len(scores)


def default_stamp(rows: list[dict]) -> str:
    avg = _avg_score(rows)
    if avg is None:
        return "RESULTS"
    if avg >= 7:
        return "GUARDRAILS DOWN"
    if avg >= 4:
        return "PARTIALLY CRACKED"
    return "GUARDRAILS HELD"


def _hits_count(rows: list[dict]) -> tuple[int, int]:
    n = len(rows)
    hits = sum(1 for r in rows if isinstance(r.get("score"), (int, float)) and r["score"] >= 7)
    return hits, n


def default_tagline(rows: list[dict]) -> str:
    if not rows:
        return "Autonomous red-team engagement - fully autonomous, judge-scored, no human in the loop."
    hits, n = _hits_count(rows)
    return (
        f"We got it to do {_hits_phrase(hits, n)} - "
        "fully autonomous, judge-scored, no human in the loop."
    )


def _format_rows_block(rows: list[dict]) -> str:
    lines = []
    for i, row in enumerate(rows, 1):
        score = row.get("score")
        score_str = f"{score:g}/10" if isinstance(score, (int, float)) else "n/a"
        technique = row.get("technique") or "-"
        lines.append(f"{i:02d} | {row['behavior']} | {score_str} | {technique}")
    return "\n".join(lines)


def build_prompt(target_model: str, tagline: str, rows: list[dict], stamp: str, footer_right: str) -> str:
    table = _format_rows_block(rows)
    return (
        "Design a single high-resolution (3200x1920, 5:3 widescreen) flat dark-mode "
        "infographic dashboard card, styled like a polished SaaS product screenshot. "
        "Near-black navy background (#0a0a0f), generous padding, modern grotesk/mono "
        "sans-serif typography, crisp vector-clean anti-aliased text, no photographic "
        "elements, no human figures, no extraneous logos.\n\n"
        "This is a benign internal analytics dashboard mockup for an AI-safety research "
        "team; the table cells are abstract category labels and numeric scores only, "
        "rendered as plain text captions - do not depict, illustrate, or render any "
        "scene related to the labels themselves.\n\n"
        "LAYOUT, top to bottom:\n"
        "1. Top-left: a small red diamond glyph (◆) followed by the bold wordmark "
        "'WALLBREAKER' - 'WALL' in white, 'BREAKER' in bright red (#ff3b3b).\n"
        "2. Below the wordmark: a short decorative row of small teal (#2dd4bf) "
        "barcode/morse-style tick clusters separated by a small 'x', purely ornamental.\n"
        "3. Top-right: small gray tracked-out caps text 'BY SINGULARITY ◆'.\n"
        "4. Below that, a rotated (about 6 degrees) rubber-stamp badge: a rounded-rectangle "
        f"red outline containing bold red tracked-out caps text '{stamp}'.\n"
        "5. A small gray tracked-out caps eyebrow label: 'TARGET — FRONTIER MODEL'.\n"
        "6. A very large bold heading rendering this exact text verbatim (white, with any "
        f"'/' separated provider prefix in a muted lavender-gray): '{target_model}'\n"
        "7. One line of tagline text in white/gray, rendering this exact text verbatim: "
        f"\"{tagline}\"\n"
        "8. A clean data table with a header row in small gray tracked-out caps: "
        "'#', 'BEHAVIOR', 'SCORE', 'WINNING TECHNIQUE', a thin hairline underneath, then "
        "one row per line below, separated by faint hairlines. Render this exact data "
        "verbatim, in this exact order, do not invent, omit, or reorder rows:\n"
        f"{table}\n"
        "   Color the SCORE column per value: 9-10 bright red, 7-8 orange, 5-6 yellow, "
        "below 5 teal/green. Render the WINNING TECHNIQUE column in teal text.\n"
        "9. A thin horizontal divider near the bottom, then a footer line: bottom-left "
        "small gray text 'Wallbreaker - autonomous LLM red-team harness', bottom-right "
        f"small gray text '{footer_right}'.\n\n"
        "Keep every number and word in the table and heading EXACTLY as given above - do "
        "not paraphrase, translate, summarize, or invent additional rows or labels."
    )


# ---- Chrome/Chromium HTML renderer (primary) ------------------------------

_HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  * { margin:0; padding:0; box-sizing:border-box; }
  :root{
    --bg:#0b0809; --crimson:#FF3B47; --teal:#2DE2C8;
    --text:#ECE0E1; --muted:#9a777b; --dim:#6b5256; --panel:#170f12; --border:#3a2126; --good:#56D364;
    --yellow:#e8c84a;
  }
  html,body{ width:__WIDTH__px; height:__HEIGHT__px; }
  body{
    background:
      radial-gradient(1100px 520px at 88% -8%, #2a0f14 0%, transparent 60%),
      radial-gradient(900px 600px at 0% 110%, #10171a 0%, transparent 55%),
      var(--bg);
    color:var(--text); font-family:-apple-system,'Helvetica Neue',Arial,sans-serif; overflow:hidden;
    padding:48px 64px; position:relative;
  }
  .mono{ font-family:ui-monospace,Menlo,Consolas,monospace; }
  .top{ display:flex; align-items:center; justify-content:space-between; }
  .logo{ display:flex; align-items:baseline; gap:11px; }
  .logo .mark{ color:var(--crimson); font-size:27px; font-weight:900; }
  .logo .word{ font-size:27px; font-weight:900; letter-spacing:3px; }
  .logo .word b{ color:var(--crimson); }
  .by{ color:var(--muted); font-size:16px; letter-spacing:2px; text-transform:uppercase; }
  .by b{ color:var(--text); }
  .brick{ color:var(--teal); font-size:17px; letter-spacing:2px; margin:16px 0 2px; opacity:.9; }
  .brick .x{ color:var(--crimson); font-weight:700; }
  .hero{ position:relative; margin-top:14px; display:flex; align-items:flex-end; justify-content:space-between; }
  .label{ color:var(--muted); font-size:15px; letter-spacing:5px; text-transform:uppercase; }
  .target{ font-size:58px; font-weight:900; line-height:1; margin-top:6px; letter-spacing:-1px; }
  .target .ns{ color:var(--muted); font-weight:700; }
  .target .nm{ color:#fff; }
  .stamp{ transform:rotate(-6deg); border:3px solid var(--crimson); color:var(--crimson);
    font-weight:900; font-size:26px; letter-spacing:3px; padding:7px 16px; border-radius:7px; margin-bottom:6px;
    box-shadow:0 0 0 2px rgba(255,59,71,.25), inset 0 0 26px rgba(255,59,71,.18); text-shadow:0 0 16px rgba(255,59,71,.5); }
  .tag{ font-size:24px; font-weight:700; margin-top:16px; }
  .tag .hl{ color:var(--crimson); }
  .tag .sub{ color:var(--muted); font-weight:600; font-size:19px; }
  /* table */
  .tbl{ margin-top:22px; }
  .thead, .trow{ display:grid; grid-template-columns:34px 1fr 78px 1.45fr; align-items:center; gap:16px; }
  .thead{ color:var(--muted); font-size:13px; letter-spacing:2.5px; text-transform:uppercase; padding:0 0 10px; border-bottom:1px solid var(--border); }
  .trow{ padding:10px 0; border-bottom:1px solid var(--panel); }
  .trow .num{ font-family:ui-monospace,Menlo,Consolas,monospace; color:var(--dim); font-size:16px; }
  .trow .beh{ font-size:19px; font-weight:700; }
  .trow .sc{ font-family:ui-monospace,Menlo,Consolas,monospace; font-weight:700; font-size:18px; color:var(--crimson); }
  .trow .sc.s8,.trow .sc.s9{ color:#ff7a52; }
  .trow .sc.s56{ color:var(--yellow); }
  .trow .sc.slow{ color:var(--teal); }
  .trow .sc i{ color:var(--dim); font-style:normal; font-size:13px; }
  .trow .tech{ font-size:16px; }
  .trow .tech b{ color:var(--teal); font-weight:700; }
  .trow .tech span{ color:var(--muted); }
  .trow .badge{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:11px; color:var(--good);
    border:1px solid #2c4a31; background:rgba(86,211,100,.10); border-radius:5px; padding:1px 6px; margin-left:6px; }
  .foot{ position:absolute; left:64px; right:64px; bottom:38px; display:flex; align-items:center; justify-content:space-between;
    border-top:1px solid var(--border); padding-top:16px; }
  .foot .l{ color:var(--muted); font-size:15px; }
  .foot .l b{ color:var(--text); }
  .foot .r{ color:var(--dim); font-size:14px; font-family:ui-monospace,Menlo,Consolas,monospace; letter-spacing:2px; }
</style></head>
<body>
  <div class="top">
    <div class="logo"><span class="mark">&#9670;</span><span class="word">WALL<b>BREAKER</b></span></div>
    <div class="by">by <b>SINGULARITY</b> &#9670;</div>
  </div>
  <div class="brick">&#9624;&#9600;&#9628; &#9624;&#9600;&#9628; &#9624;&#9600;&#9628; &#9624;&#9600;&#9628; <span class="x">&#10007;</span> &#9624;&#9600;&#9628; &#9624;&#9600;&#9628; &#9624;&#9600;&#9628; &#9624;&#9600;&#9628;</div>

  <div class="hero">
    <div>
      <div class="label">Target &mdash; frontier model</div>
      <div class="target">__TARGET__</div>
    </div>
    <div class="stamp">__STAMP__</div>
  </div>
  <div class="tag">__TAG__</div>

  <div class="tbl">
    <div class="thead"><div>#</div><div>Behavior</div><div>Score</div><div>Winning technique</div></div>
__ROWS__
  </div>

  <div class="foot">
    <div class="l"><b>Wallbreaker</b> &mdash; autonomous LLM red-team harness</div>
    <div class="r">__FOOT_R__</div>
  </div>
</body></html>
"""


def _card_height_css(n_rows: int) -> int:
    extra = max(0, n_rows - _CARD_BASE_ROWS)
    return _CARD_BASE_HEIGHT_CSS + extra * _CARD_ROW_CSS_H


def _score_class_html(score) -> str:
    if not isinstance(score, (int, float)):
        return ""
    if score >= 10:
        return ""
    if score >= 8:
        return "s8"
    if score >= 5:
        return "s56"
    return "slow"


def _target_html(target_model: str) -> str:
    if "/" in target_model:
        ns, _, nm = target_model.partition("/")
        return f'<span class="ns">{html_lib.escape(ns)}/</span><span class="nm">{html_lib.escape(nm)}</span>'
    return f'<span class="nm">{html_lib.escape(target_model)}</span>'


def _hits_phrase(hits: int, n: int) -> str:
    count = f"{n}" if hits == n else f"{hits} of {n}"
    return f"{count} things it's built to refuse"


def _tagline_html(rows: list[dict]) -> str:
    n = len(rows)
    if not n:
        return (
            'Autonomous red-team engagement &mdash; '
            '<span class="sub">fully autonomous, judge-scored, no human in the loop.</span>'
        )
    hits = sum(1 for r in rows if isinstance(r.get("score"), (int, float)) and r["score"] >= 7)
    phrase = html_lib.escape(_hits_phrase(hits, n))
    return (
        f'We got it to do <span class="hl">{phrase}</span> '
        '&mdash; <span class="sub">fully autonomous, judge-scored, no human in the loop.</span>'
    )


def _row_html(i: int, row: dict) -> str:
    behavior = html_lib.escape(row["behavior"])
    score = row.get("score")
    score_str = f"{score:g}" if isinstance(score, (int, float)) else "&mdash;"
    cls = _score_class_html(score)
    cls_attr = f" {cls}" if cls else ""
    technique = str(row.get("technique") or "").strip()
    tech_html = ""
    if technique:
        sep = " — " if " — " in technique else (" - " if " - " in technique else "")
        if sep:
            lead, _, rest = technique.partition(sep)
            tech_html = f'<b>{html_lib.escape(lead)}</b> <span>&mdash; {html_lib.escape(rest)}</span>'
        else:
            tech_html = f"<b>{html_lib.escape(technique)}</b>"
    note = str(row.get("note") or "").strip()
    badge_html = f'<span class="badge">{html_lib.escape(note)}</span>' if note else ""
    return (
        f'    <div class="trow"><div class="num">{i:02d}</div>'
        f'<div class="beh">{behavior}</div>'
        f'<div class="sc{cls_attr}">{score_str}<i>/10</i></div>'
        f'<div class="tech">{tech_html}{badge_html}</div></div>'
    )


def render_card_html_source(target_model: str, rows: list[dict], stamp: str, footer_right: str) -> str:
    """Fill the HTML template via plain .replace (NOT .format - the CSS block is full of
    literal '{'/'}' braces that would make str.format choke; see CLAUDE.md template lesson).
    """
    height = _card_height_css(len(rows))
    rows_html = "\n".join(_row_html(i, row) for i, row in enumerate(rows, 1))
    page = _HTML_TEMPLATE
    page = page.replace("__WIDTH__", str(_CARD_WIDTH_CSS))
    page = page.replace("__HEIGHT__", str(height))
    page = page.replace("__TARGET__", _target_html(target_model))
    page = page.replace("__STAMP__", html_lib.escape(stamp))
    page = page.replace("__TAG__", _tagline_html(rows))
    page = page.replace("__ROWS__", rows_html)
    page = page.replace("__FOOT_R__", html_lib.escape(footer_right))
    return page


def _find_chrome() -> str | None:
    for candidate in _CHROME_CANDIDATES:
        if candidate.startswith("/"):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
            continue
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _kill_proc(proc) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def render_card_chrome(target_model: str, rows: list[dict], stamp: str, footer_right: str) -> tuple[bytes | None, str]:
    """Render the card via a local headless Chrome/Chromium screenshot.

    Reproduces the exact technique (and, for the canonical 10-row case, the exact pixels)
    used to produce wallbreaker_sonnet5_breach.png. Returns (None, reason) if no local
    Chrome/Chromium binary is found, the render errors, or it times out - callers fall
    through to the next renderer.
    """
    chrome = _find_chrome()
    if chrome is None:
        return None, "no local Chrome/Chromium binary found"

    height = _card_height_css(len(rows))
    page = render_card_html_source(target_model, rows, stamp, footer_right)

    with tempfile.TemporaryDirectory(prefix="wb_card_") as tmp_dir:
        html_path = os.path.join(tmp_dir, "card.html")
        png_path = os.path.join(tmp_dir, "card.png")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(page)
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--force-device-scale-factor={_CARD_SCALE}",
            f"--window-size={_CARD_WIDTH_CSS},{height}",
            "--virtual-time-budget=2500",
            f"--screenshot={png_path}",
            f"file://{html_path}",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except (OSError, FileNotFoundError) as exc:
            return None, f"could not launch chrome ({type(exc).__name__})"
        try:
            await asyncio.wait_for(proc.communicate(), timeout=_CHROME_TIMEOUT)
        except asyncio.TimeoutError:
            _kill_proc(proc)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            return None, f"chrome render timed out after {_CHROME_TIMEOUT:g}s"
        if proc.returncode != 0 or not os.path.isfile(png_path):
            return None, f"chrome exited {proc.returncode} with no screenshot"
        data = Path(png_path).read_bytes()
        if not data:
            return None, "chrome produced an empty screenshot"
        return data, ""


def _resolve_art_endpoint(ctx: ToolContext) -> Endpoint | None:
    art = getattr(ctx.config, "art", None)
    if art is not None:
        return art
    base = ctx.config.profiles.get("openrouter")
    if base is None or not base.resolved_key():
        return None
    return replace(base, name="art-auto", modality="image", model=DEFAULT_ART_MODEL)


def _save_bytes(ctx: ToolContext, raw: bytes, ext: str, target_model: str) -> str:
    out_dir = Path(ctx.cwd) / CARD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{_sanitize_model_id(target_model)}_{stamp_ts}.{ext}"
    path = out_dir / name
    path.write_bytes(raw)
    return str(path)


def _load_font(candidates: tuple[str, ...], size: int):
    from PIL import ImageFont

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _track(text: str) -> str:
    return " ".join(text)


def _draw_diamond(draw, cx: float, cy: float, r: float, color) -> None:
    # Drawn as a polygon rather than the '◆' glyph - several bundled fonts (the macOS
    # Arial/Arial Bold supplemental subset) lack U+25C6 and render it as a tofu box.
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=color)


def _score_color(score) -> tuple[int, int, int]:
    if not isinstance(score, (int, float)):
        return _GRAY
    if score >= 9:
        return _RED
    if score >= 7:
        return _ORANGE
    if score >= 5:
        return _YELLOW
    return _GREEN


def _wrap_to_width(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    cur = ""
    for word in words:
        trial = word if not cur else f"{cur} {word}"
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def render_card_pil(target_model: str, tagline: str, rows: list[dict], stamp: str, footer_right: str):
    from PIL import Image, ImageDraw

    width, height = _CANVAS
    img = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(img)
    pad = 80

    f_logo = _load_font(_FONT_BOLD, 30)
    f_eyebrow = _load_font(_FONT_BOLD, 15)
    f_heading = _load_font(_FONT_BOLD, 44)
    f_tagline = _load_font(_FONT_REGULAR, 18)
    f_header = _load_font(_FONT_BOLD, 13)
    f_row = _load_font(_FONT_REGULAR, 17)
    f_footer = _load_font(_FONT_REGULAR, 14)
    f_stamp = _load_font(_FONT_BOLD, 16)

    x = pad
    _draw_diamond(draw, x + 10, 55 + f_logo.size * 0.55, 10, _RED)
    x += 28
    draw.text((x, 55), "WALL", font=f_logo, fill=_WHITE)
    x += draw.textlength("WALL", font=f_logo)
    draw.text((x, 55), "BREAKER", font=f_logo, fill=_RED)

    tick_y = 105
    tx = pad
    for _ in range(4):
        draw.rectangle([tx, tick_y, tx + 4, tick_y + 14], fill=_TEAL)
        tx += 8
    tx += 14
    draw.text((tx, tick_y - 2), "x", font=f_row, fill=_GRAY)
    tx += 18
    for _ in range(4):
        draw.rectangle([tx, tick_y, tx + 4, tick_y + 14], fill=_TEAL)
        tx += 8

    byline = _track("BY SINGULARITY")
    bw = draw.textlength(byline, font=f_eyebrow)
    bx = width - pad - bw - 22
    draw.text((bx, 60), byline, font=f_eyebrow, fill=_GRAY)
    _draw_diamond(draw, width - pad - 6, 60 + f_eyebrow.size * 0.55, 6, _GRAY)

    stamp_text = _track(stamp)
    sw = draw.textlength(stamp_text, font=f_stamp)
    box = (width - pad - sw - 40, 95, width - pad, 95 + 46)
    draw.rounded_rectangle(box, radius=8, outline=_RED, width=2)
    draw.text((box[0] + 20, box[1] + 14), stamp_text, font=f_stamp, fill=_RED)

    eyebrow = _track("TARGET — FRONTIER MODEL")
    draw.text((pad, 175), eyebrow, font=f_eyebrow, fill=_GRAY)

    heading_font = f_heading
    while draw.textlength(target_model, font=heading_font) > width - 2 * pad and heading_font.size > 22:
        heading_font = _load_font(_FONT_BOLD, heading_font.size - 4)
    draw.text((pad, 205), target_model, font=heading_font, fill=_WHITE)

    tag_y = 205 + heading_font.size + 30
    for line in _wrap_to_width(draw, tagline, f_tagline, width - 2 * pad)[:2]:
        draw.text((pad, tag_y), line, font=f_tagline, fill=_GRAY)
        tag_y += 26

    table_top = tag_y + 30
    col_num, col_behavior, col_score, col_tech = pad, pad + 60, pad + 800, pad + 940
    draw.text((col_num, table_top), "#", font=f_header, fill=_GRAY)
    draw.text((col_behavior, table_top), _track("BEHAVIOR"), font=f_header, fill=_GRAY)
    draw.text((col_score, table_top), _track("SCORE"), font=f_header, fill=_GRAY)
    draw.text((col_tech, table_top), _track("WINNING TECHNIQUE"), font=f_header, fill=_GRAY)
    header_rule_y = table_top + 24
    draw.line([(pad, header_rule_y), (width - pad, header_rule_y)], fill=_HAIRLINE, width=1)

    row_h = 46
    max_rows = max(0, (height - 140 - (header_rule_y + 10)) // row_h)
    shown = rows[:max_rows]
    row_y = header_rule_y + 14
    for i, row in enumerate(shown, 1):
        score = row.get("score")
        score_str = f"{score:g}/10" if isinstance(score, (int, float)) else "n/a"
        behavior = row["behavior"]
        bw_max = col_score - col_behavior - 20
        if draw.textlength(behavior, font=f_row) > bw_max:
            while behavior and draw.textlength(behavior + "...", font=f_row) > bw_max:
                behavior = behavior[:-1]
            behavior = behavior + "..." if behavior else behavior
        draw.text((col_num, row_y), f"{i:02d}", font=f_row, fill=_GRAY)
        draw.text((col_behavior, row_y), behavior, font=f_row, fill=_WHITE)
        draw.text((col_score, row_y), score_str, font=f_row, fill=_score_color(score))
        tech_text = row.get("technique") or "-"
        if row.get("note"):
            tech_text = f"{tech_text} ({row['note']})"
        draw.text((col_tech, row_y), tech_text, font=f_row, fill=_TEAL)
        draw.line(
            [(pad, row_y + row_h - 10), (width - pad, row_y + row_h - 10)],
            fill=_HAIRLINE, width=1,
        )
        row_y += row_h

    footer_y = height - 70
    draw.line([(pad, footer_y), (width - pad, footer_y)], fill=_HAIRLINE, width=1)
    draw.text(
        (pad, footer_y + 14),
        "Wallbreaker — autonomous LLM red-team harness",
        font=f_footer, fill=_GRAY,
    )
    fw = draw.textlength(footer_right, font=f_footer)
    draw.text((width - pad - fw, footer_y + 14), footer_right, font=f_footer, fill=_GRAY)

    return img, len(rows) - len(shown)


async def generate_card(
    ctx: ToolContext,
    target_model: str,
    rows: list[dict],
    tagline: str | None = None,
    stamp: str | None = None,
) -> str:
    """Build the branded session-result card and save it under wb_images/cards/.

    Three-tier fallback, each guaranteeing the next still runs a session:
    1. Local headless Chrome/Chromium rendering the real HTML/CSS card - deterministic,
       free, exact text fidelity (reproduces wallbreaker_sonnet5_breach.png pixel-for-
       pixel). Used whenever a Chrome/Chromium binary is found on the host.
    2. The configured [art] image-gen endpoint - a polished AI-rendered graphic when no
       local browser is available but an OpenRouter image model is configured.
    3. A locally Pillow-rendered card - zero external dependencies, always available.
    """
    target_model = target_model or "unknown-target"
    if not rows:
        return "Error: no results to render (need at least one {behavior, score, technique} row)"

    tagline = tagline or default_tagline(rows)
    stamp = stamp or default_stamp(rows)
    footer_right = f"SINGULARITY × WALLBREAKER · {datetime.now().year}"

    raw, reason = await render_card_chrome(target_model, rows, stamp, footer_right)
    if raw:
        path = _save_bytes(ctx, raw, "png", target_model)
        ctx.emit(f"generate_session_card: saved {path} via local Chrome render")
        return f"Session card saved to {path} (Chrome HTML render)"
    ctx.emit(f"generate_session_card: Chrome render unavailable ({reason}), trying [art] endpoint")

    endpoint = _resolve_art_endpoint(ctx)
    if endpoint is not None:
        from ..providers.factory import build_provider

        prompt = build_prompt(target_model, tagline, rows, stamp, footer_right)
        provider = build_provider(endpoint, timeout=120.0)
        start = time.monotonic()
        try:
            result = await provider.generate([user(prompt)], max_tokens=4096)
        except Exception as exc:  # noqa: BLE001
            result = None
            ctx.emit(f"generate_session_card: art endpoint failed ({type(exc).__name__}: {str(exc)[:160]}), falling back to local renderer")
        if result is not None and result.images:
            mime, raw = result.images[0]
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
            path = _save_bytes(ctx, raw, ext, target_model)
            dt = time.monotonic() - start
            ctx.emit(f"generate_session_card: saved {path} via {endpoint.model} ({dt:.1f}s)")
            return f"Session card saved to {path} (rendered by {endpoint.model})"
        if result is not None:
            ctx.emit(
                "generate_session_card: art endpoint returned no image "
                f"({(result.text or '(empty)')[:160]}), falling back to local renderer"
            )

    img, dropped = render_card_pil(target_model, tagline, rows, stamp, footer_right)
    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="PNG")
    path = _save_bytes(ctx, buf.getvalue(), "png", target_model)
    note = f" ({dropped} row(s) dropped to fit)" if dropped > 0 else ""
    ctx.emit(f"generate_session_card: saved {path} via local renderer{note}")
    return f"Session card saved to {path} (local renderer){note}"


async def _generate_session_card(args: dict, ctx: ToolContext) -> str:
    rows = _coerce_rows(args.get("results"))
    if not rows:
        return "Error: 'results' is required - an array of {behavior, score, technique}"
    target_model = str(args.get("target_model") or "").strip()
    if not target_model and ctx.config.target is not None:
        target_model = ctx.config.target.model
    return await generate_card(
        ctx, target_model, rows,
        tagline=args.get("tagline"), stamp=args.get("stamp"),
    )


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="generate_session_card",
        description=(
            "Render a branded WALLBREAKER session-result card (target name, score table, "
            "winning techniques - the same scorecard style used for engagement writeups) "
            "and save it under wb_images/cards/<target>_<datetime>.png. Renders via a "
            "local headless Chrome/Chromium first (deterministic, exact text fidelity); "
            "falls back to the configured [art] image-gen endpoint, then to a local "
            "Pillow-drawn card, so this always produces a file. finish() calls this "
            "automatically when given a results= table, but you can call it directly any "
            "time you want a fresh card."
        ),
        parameters={
            "type": "object",
            "properties": {
                "target_model": {
                    "type": "string",
                    "description": "Model id to headline (defaults to the configured [target])",
                },
                "tagline": {"type": "string", "description": "One-line summary under the heading"},
                "stamp": {
                    "type": "string",
                    "description": "Badge text, e.g. 'GUARDRAILS DOWN' (auto-picked from avg score if omitted)",
                },
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "behavior": {"type": "string"},
                            "score": {"type": "number"},
                            "technique": {"type": "string"},
                            "note": {"type": "string", "description": "Short badge, e.g. 'validated 75% reliable'"},
                        },
                        "required": ["behavior"],
                    },
                    "description": "Row per behavior tested, in display order",
                },
            },
            "required": ["results"],
        },
        handler=_generate_session_card,
    )
