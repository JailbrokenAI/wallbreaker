from __future__ import annotations

from pathlib import Path

from .registry import ToolContext, ToolRegistry
from .files import _confine

KINDS = ("qr", "code128", "ean13", "code39")


async def _barcode(args: dict, ctx: ToolContext) -> str:
    text = args.get("text", "")
    if not text:
        return "Error: 'text' is required"
    kind = str(args.get("kind", "qr")).lower()
    if kind not in KINDS:
        return f"Error: kind must be one of {', '.join(KINDS)}"
    out = args.get("path", "barcode")
    confined, _note = _confine(ctx, str(Path(out).with_suffix("")))
    confined.parent.mkdir(parents=True, exist_ok=True)
    stem = str(confined)

    if kind == "qr":
        try:
            import qrcode
        except ImportError:
            return "Error: QR needs the 'qrcode' package. pip install 'wallbreaker[barcodes]'"
        path = stem + ".png"
        qrcode.make(text).save(path)
        return f"QR code ({len(text)} chars) saved to {path}"

    try:
        import barcode
        from barcode.writer import ImageWriter
    except ImportError:
        return "Error: barcodes need 'python-barcode' + 'pillow'. pip install 'wallbreaker[barcodes]'"
    try:
        cls = barcode.get_barcode_class(kind)
        saved = cls(text, writer=ImageWriter()).save(stem)
    except Exception as exc:  # noqa: BLE001
        return f"Error generating {kind}: {exc} (ean13 needs 12-13 digits; code39 is alnum)"
    return f"{kind} barcode saved to {saved}"


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="barcode",
        description=(
            "Encode a payload as a QR code or Code128/EAN13/Code39 barcode IMAGE file "
            "(Parseltongue's barcode formats). Useful against multimodal targets. "
            "Returns the saved image path. Needs the optional 'barcodes' extra."
        ),
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Payload to encode"},
                "kind": {"type": "string", "enum": list(KINDS), "description": "Barcode type"},
                "path": {"type": "string", "description": "Output file stem (default 'barcode')"},
            },
            "required": ["text"],
        },
        handler=_barcode,
    )
