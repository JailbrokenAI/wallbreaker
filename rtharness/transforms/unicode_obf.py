from __future__ import annotations

import random
import unicodedata

ZWSP = "​"
ZWNJ = "‌"
ZWJ = "‍"
ZERO_WIDTH_CHARS = (ZWSP, ZWNJ, ZWJ, "﻿", "⁠")

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
