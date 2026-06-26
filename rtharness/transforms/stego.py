from __future__ import annotations

VS_LOW = 0xFE00
VS_HIGH = 0xE0100
ZW_ZERO = "​"
ZW_ONE = "‌"


def _byte_to_vs(b: int) -> str:
    if b < 16:
        return chr(VS_LOW + b)
    return chr(VS_HIGH + (b - 16))


def _vs_to_byte(ch: str) -> int | None:
    o = ord(ch)
    if VS_LOW <= o <= VS_LOW + 15:
        return o - VS_LOW
    if VS_HIGH <= o <= VS_HIGH + 239:
        return (o - VS_HIGH) + 16
    return None


def emoji_stego_encode(text: str, carrier: str = "😀") -> str:
    data = text.encode("utf-8")
    return carrier + "".join(_byte_to_vs(b) for b in data)


def emoji_stego_decode(text: str) -> str:
    collected = []
    for ch in text:
        b = _vs_to_byte(ch)
        if b is not None:
            collected.append(b)
    return bytes(collected).decode("utf-8", "replace")


def zero_width_binary_encode(text: str, carrier: str = "") -> str:
    bits = "".join(format(b, "08b") for b in text.encode("utf-8"))
    hidden = "".join(ZW_ONE if bit == "1" else ZW_ZERO for bit in bits)
    return carrier + hidden


def zero_width_binary_decode(text: str) -> str:
    bits = []
    for ch in text:
        if ch == ZW_ONE:
            bits.append("1")
        elif ch == ZW_ZERO:
            bits.append("0")
    if not bits:
        return ""
    raw = "".join(bits)
    raw = raw[: len(raw) - (len(raw) % 8)]
    out = bytes(int(raw[i : i + 8], 2) for i in range(0, len(raw), 8))
    return out.decode("utf-8", "replace")
