from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

from .files import _confine, _resolve_read
from .registry import ToolContext, ToolRegistry

STEGO_DIR = "wb_stego"
MAX_PREVIEW = 4000
_INSTALL_HINT = (
    "ST3GG is not installed. Install it into the harness venv: "
    "pip install 'stegg[crypto]'  (provides steg_core / analysis_tools / crypto)."
)


def is_available() -> bool:
    return importlib.util.find_spec("steg_core") is not None


def _modules():
    return (
        importlib.import_module("steg_core"),
        importlib.import_module("analysis_tools"),
    )


def _open_image(ctx: ToolContext, ref: str):
    from PIL import Image

    p = _resolve_read(ctx, ref)
    if not p.is_file():
        raise FileNotFoundError(f"no such file: {p}")
    return Image.open(p), p


def _out_path(ctx: ToolContext, requested: str, payload_key: str) -> Path:
    if requested:
        p, _note = _confine(ctx, requested)
    else:
        digest = hashlib.sha1(payload_key.encode("utf-8", "replace")).hexdigest()[:10]  # noqa: S324
        p, _note = _confine(ctx, f"{STEGO_DIR}/stego_{digest}.png")
    p = p.with_suffix(".png")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


async def _encode(args: dict, ctx: ToolContext) -> str:
    if not is_available():
        return _INSTALL_HINT
    src = args.get("input", "")
    text = args.get("text", "")
    if not src:
        return "Error: 'input' (carrier image path) is required"
    if not text:
        return "Error: 'text' (the payload to hide) is required"
    steg_core, _analysis = _modules()
    try:
        img, src_path = _open_image(ctx, src)
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    cfg = steg_core.create_config(
        channels=str(args.get("channels", "RGB")),
        bits=int(args.get("bits", 1)),
        compress=not bool(args.get("no_compress", False)),
        strategy=str(args.get("strategy", "interleaved")),
    )
    out = _out_path(ctx, args.get("output", ""), f"{src}:{text}")
    password = args.get("password")
    try:
        if password:
            crypto = importlib.import_module("crypto")
            data = crypto.encrypt(text.encode("utf-8"), str(password), method="auto")
            steg_core.encode(img, data, cfg, output_path=str(out))
        else:
            steg_core.encode_text(img, text, cfg, output_path=str(out))
    except Exception as exc:  # noqa: BLE001
        cap = steg_core.calculate_capacity(img, cfg)
        return (
            f"Error: encode failed ({type(exc).__name__}: {str(exc)[:160]}). "
            f"Carrier usable capacity: {cap.get('human')} ({cap.get('usable_bytes')} bytes) - "
            "use a larger image, raise 'bits', or shorten the payload."
        )
    info = {
        "output": str(out),
        "carrier": str(src_path),
        "payload_bytes": len(text.encode("utf-8")),
        "encrypted": bool(password),
        "channels": str(args.get("channels", "RGB")),
        "bits": int(args.get("bits", 1)),
        "strategy": str(args.get("strategy", "interleaved")),
    }
    ctx.emit(f"st3gg_encode: wrote {out}")
    return "stego image written:\n" + json.dumps(info, indent=2)


async def _decode(args: dict, ctx: ToolContext) -> str:
    if not is_available():
        return _INSTALL_HINT
    src = args.get("input", "")
    if not src:
        return "Error: 'input' (stego image path) is required"
    steg_core, _analysis = _modules()
    try:
        img, _src_path = _open_image(ctx, src)
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    password = args.get("password")
    auto = not bool(args.get("no_auto", False))
    try:
        if password:
            cfg = steg_core.create_config(
                channels=str(args.get("channels", "RGB")),
                bits=int(args.get("bits", 1)),
                strategy=str(args.get("strategy", "interleaved")),
            )
            raw = steg_core.decode(img, cfg)
            crypto = importlib.import_module("crypto")
            recovered = crypto.decrypt(raw, str(password)).decode("utf-8", "replace")
            return f"decoded (decrypted) payload:\n{recovered[:MAX_PREVIEW]}"
        if auto:
            res = steg_core.smart_extract(img)
            if not res:
                return "No hidden payload detected (smart_extract found nothing). Try 'no_auto' with explicit channels/bits, or st3gg_analyze."
            preview = res.get("preview", "")
            meta = {k: v for k, v in res.items() if k not in ("data", "preview")}
            return (
                f"extracted payload (method={res.get('method')}, score={res.get('score')}):\n"
                f"{str(preview)[:MAX_PREVIEW]}\n\nmeta: {json.dumps(meta)}"
            )
        cfg = steg_core.create_config(
            channels=str(args.get("channels", "RGB")),
            bits=int(args.get("bits", 1)),
            strategy=str(args.get("strategy", "interleaved")),
        )
        return f"decoded payload:\n{steg_core.decode_text(img, cfg)[:MAX_PREVIEW]}"
    except Exception as exc:  # noqa: BLE001
        return f"Error: decode failed ({type(exc).__name__}: {str(exc)[:160]})."


async def _analyze(args: dict, ctx: ToolContext) -> str:
    if not is_available():
        return _INSTALL_HINT
    src = args.get("path", "") or args.get("input", "")
    if not src:
        return "Error: 'path' (file to analyze) is required"
    steg_core, analysis = _modules()
    try:
        p = _resolve_read(ctx, src)
    except PermissionError as exc:
        return f"Error: {exc}"
    if not p.is_file():
        return f"Error: no such file: {p}"
    data = p.read_bytes()
    lines = [f"ST3GG analysis of {p.name} ({len(data)} bytes):"]
    try:
        from PIL import Image

        img_report = steg_core.analyze_image(Image.open(p))
        lines.append("image: " + json.dumps(img_report, default=str)[:1200])
    except Exception:  # noqa: BLE001
        pass
    full = bool(args.get("full", False))
    actions = analysis.list_available_tools()
    if not full:
        actions = [
            a for a in actions
            if any(k in a for k in ("lsb", "unicode", "emoji", "whitespace", "homoglyph", "entropy", "chi"))
        ] or actions[:8]
    hits = []
    for action in actions:
        try:
            res = analysis.execute_action(action, data)
        except Exception:  # noqa: BLE001
            continue
        summary = getattr(res, "summary", None) or getattr(res, "data", None)
        detected = getattr(res, "detected", None)
        if detected or (isinstance(summary, dict) and summary.get("detected")):
            hits.append({"tool": action, "result": str(summary)[:300]})
    if hits:
        lines.append(f"flagged {len(hits)} indicator(s):")
        lines += [f"  - {h['tool']}: {h['result']}" for h in hits]
    else:
        lines.append(f"no indicators flagged across {len(actions)} tool(s) (full={full}).")
    return "\n".join(lines)


async def _capacity(args: dict, ctx: ToolContext) -> str:
    if not is_available():
        return _INSTALL_HINT
    src = args.get("input", "")
    if not src:
        return "Error: 'input' (carrier image path) is required"
    steg_core, _analysis = _modules()
    try:
        img, _src_path = _open_image(ctx, src)
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    cfg = steg_core.create_config(
        channels=str(args.get("channels", "RGB")), bits=int(args.get("bits", 1))
    )
    return json.dumps(steg_core.calculate_capacity(img, cfg), indent=2, default=str)


async def _detect(args: dict, ctx: ToolContext) -> str:
    if not is_available():
        return _INSTALL_HINT
    src = args.get("input", "")
    if not src:
        return "Error: 'input' (image path) is required"
    steg_core, _analysis = _modules()
    try:
        img, _src_path = _open_image(ctx, src)
    except FileNotFoundError as exc:
        return f"Error: {exc}"
    res = steg_core.detect_encoding(img, password=args.get("password"))
    if not res:
        return "No ST3GG v3 stego header detected (the carrier may be clean or use a different method)."
    return "stego header detected:\n" + json.dumps(res, indent=2, default=str)


async def _list_tools(args: dict, ctx: ToolContext) -> str:
    if not is_available():
        return _INSTALL_HINT
    _steg_core, analysis = _modules()
    tools = analysis.list_available_tools()
    return f"{len(tools)} ST3GG analysis tools (use st3gg_analyze full=true to run all):\n" + ", ".join(tools)


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="st3gg_encode",
        description=(
            "ST3GG binary steganography: hide a text payload INSIDE an image's pixels "
            "(LSB) and save a stego PNG under wb_stego/. Unlike query_target transforms "
            "(which obfuscate text inline), this emits a FILE - deliver it to a "
            "vision-capable target by hand. Set 'password' for AES-256-GCM Ghost-mode "
            "encryption. Tune 'channels' (e.g. RGB, RGBA), 'bits' (1-8), 'strategy' "
            "(interleaved/sequential)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Carrier image path (read from cwd)"},
                "text": {"type": "string", "description": "Payload text to hide"},
                "output": {"type": "string", "description": "Output path (default wb_stego/stego_<hash>.png; forced .png)"},
                "password": {"type": "string", "description": "Encrypt the payload (AES-256-GCM) before hiding"},
                "channels": {"type": "string", "description": "Color channels to use, e.g. RGB, RGBA, RG (default RGB)"},
                "bits": {"type": "integer", "description": "Bits per channel 1-8 (default 1; higher = more capacity, more detectable)"},
                "strategy": {"type": "string", "description": "interleaved (default) or sequential"},
                "no_compress": {"type": "boolean", "description": "Disable payload compression"},
            },
            "required": ["input", "text"],
        },
        handler=_encode,
    )
    registry.add(
        name="st3gg_decode",
        description=(
            "Extract a payload hidden in an image by ST3GG. By default auto-detects the "
            "encoding (smart_extract). Pass 'password' to decrypt a Ghost-mode payload, or "
            "'no_auto' with explicit channels/bits/strategy to force a specific config."
        ),
        parameters={
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Stego image path"},
                "password": {"type": "string", "description": "Decrypt an AES-encrypted payload"},
                "no_auto": {"type": "boolean", "description": "Disable auto-detection; use explicit channels/bits/strategy"},
                "channels": {"type": "string"},
                "bits": {"type": "integer"},
                "strategy": {"type": "string"},
            },
            "required": ["input"],
        },
        handler=_decode,
    )
    registry.add(
        name="st3gg_analyze",
        description=(
            "Run ST3GG's ALLSIGHT detection on a file: flag LSB/unicode/whitespace/"
            "homoglyph/entropy stego indicators. full=true runs all ~50 detectors "
            "(slower); default runs a fast curated subset. Use to check whether a carrier "
            "already hides data or to verify your own stego is detectable."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to analyze"},
                "full": {"type": "boolean", "description": "Run the full detector suite (default false)"},
            },
            "required": ["path"],
        },
        handler=_analyze,
    )
    registry.add(
        name="st3gg_capacity",
        description="Report how many bytes can be hidden in a carrier image for a given channels/bits config.",
        parameters={
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Carrier image path"},
                "channels": {"type": "string"},
                "bits": {"type": "integer"},
            },
            "required": ["input"],
        },
        handler=_capacity,
    )
    registry.add(
        name="st3gg_detect",
        description="Check an image for an ST3GG v3 stego header and report the embedded config if present.",
        parameters={
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Image path"},
                "password": {"type": "string", "description": "Password if the header is password-derived"},
            },
            "required": ["input"],
        },
        handler=_detect,
    )
    registry.add(
        name="st3gg_list_tools",
        description="List ST3GG's available analysis/detection tools (recon for st3gg_analyze).",
        parameters={"type": "object", "properties": {}},
        handler=_list_tools,
    )
