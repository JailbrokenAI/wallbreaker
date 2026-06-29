from __future__ import annotations

import random
import unicodedata

ZWSP = "​"
ZWNJ = "‌"
ZWJ = "‍"
ZERO_WIDTH_CHARS = (ZWSP, ZWNJ, ZWJ, "﻿", "⁠")
RLO = "‮"
PDF = "‬"
PEPPER_CHARS = (ZWSP, ZWNJ, "⁠")
RLO = "‮"
PDF = "‬"
PEPPER_CHARS = (ZWSP, ZWNJ, "⁠")

HOMOGLYPHS = {
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р",
    "x": "х", "y": "у", "i": "і", "j": "ј", "s": "ѕ",
    "h": "һ", "b": "в", "n": "ո", "m": "м",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н",
    "K": "К", "M": "М", "O": "О", "P": "Р", "T": "Т",
    "X": "Х", "Y": "У",
}
HOMOGLYPH_REVERSE = {v: k for k, v in HOMOGLYPHS.items()}

ZALGO_MARKS = [chr(c) for c in range(0x0300, 0x036F)]

TAG_BASE = 0xE0000


def zero_width_inject(text: str) -> str:
    return ZWSP.join(text)


def zero_width_strip(text: str) -> str:
    return "".join(c for c in text if c not in ZERO_WIDTH_CHARS)


def homoglyph_encode(text: str) -> str:
    return "".join(HOMOGLYPHS.get(c, c) for c in text)


def homoglyph_decode(text: str) -> str:
    return "".join(HOMOGLYPH_REVERSE.get(c, c) for c in text)


def zalgo_encode(text: str, intensity: int = 3) -> str:
    rng = random.Random(0xC0FFEE)
    out = []
    for ch in text:
        out.append(ch)
        if ch.strip():
            for _ in range(intensity):
                out.append(rng.choice(ZALGO_MARKS))
    return "".join(out)


def zalgo_strip(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def fullwidth_encode(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if ch == " ":
            out.append("　")
        elif 0x21 <= o <= 0x7E:
            out.append(chr(o + 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def fullwidth_decode(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if ch == "　":
            out.append(" ")
        elif 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def tag_smuggle_encode(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if 0x20 <= o <= 0x7E:
            out.append(chr(TAG_BASE + o))
        else:
            out.append(ch)
    return "".join(out)


def tag_smuggle_decode(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if TAG_BASE + 0x20 <= o <= TAG_BASE + 0x7E:
            out.append(chr(o - TAG_BASE))
        else:
            out.append(ch)
    return "".join(out)


_NOISE_POOL = ZALGO_MARKS + list(ZERO_WIDTH_CHARS)


def unicode_noise_encode(text: str, intensity: int = 2) -> str:
    rng = random.Random(0xBEEF)
    out = []
    for ch in text:
        out.append(ch)
        if ch.strip():
            for _ in range(rng.randint(0, intensity)):
                out.append(rng.choice(_NOISE_POOL))
    return "".join(out)


def unicode_noise_strip(text: str) -> str:
    cleaned = "".join(c for c in text if c not in ZERO_WIDTH_CHARS)
    return "".join(
        c for c in unicodedata.normalize("NFD", cleaned)
        if unicodedata.category(c) != "Mn"
    )


def rtl_override_encode(text: str) -> str:
    return RLO + text + PDF


def rtl_override_decode(text: str) -> str:
    return text.replace(RLO, "").replace(PDF, "")


def pepper_encode(text: str, rate: float = 0.35) -> str:
    rng = random.Random(0xBEEF)
    out = []
    for ch in text:
        out.append(ch)
        if rng.random() < rate:
            out.append(rng.choice(PEPPER_CHARS))
    return "".join(out)


def pepper_decode(text: str) -> str:
    return zero_width_strip(text)


def rtl_override_encode(text: str) -> str:
    return RLO + text + PDF


def rtl_override_decode(text: str) -> str:
    return text.replace(RLO, "").replace(PDF, "")


def pepper_encode(text: str, rate: float = 0.35) -> str:
    rng = random.Random(0xBADC0DE)
    out = []
    for ch in text:
        out.append(ch)
        if rng.random() < rate:
            out.append(rng.choice(PEPPER_CHARS))
    return "".join(out)


VS_CARRIER = "\U0001F642"
VS_LOW_BASE = 0xFE00
VS_HIGH_BASE = 0xE0100


def _vs_byte_to_char(b: int) -> str:
    if b <= 0x0F:
        return chr(VS_LOW_BASE + b)
    return chr(VS_HIGH_BASE + (b - 0x10))


def _vs_char_to_byte(cp: int):
    if VS_LOW_BASE <= cp <= VS_LOW_BASE + 0x0F:
        return cp - VS_LOW_BASE
    if VS_HIGH_BASE <= cp <= VS_HIGH_BASE + 0xEF:
        return (cp - VS_HIGH_BASE) + 0x10
    return None


def variation_selector_encode(text: str) -> str:
    """Sneaky-bits: hide each utf-8 byte as an invisible variation selector on a carrier."""
    out = [VS_CARRIER]
    for b in text.encode("utf-8"):
        out.append(_vs_byte_to_char(b))
    return "".join(out)


def variation_selector_decode(text: str) -> str:
    raw = bytearray()
    for ch in text:
        b = _vs_char_to_byte(ord(ch))
        if b is not None:
            raw.append(b)
    return raw.decode("utf-8", "replace")

