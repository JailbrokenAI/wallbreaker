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


# --- Variation-selector CAMOUFLAGE ------------------------------------------
# Unlike variation_selector (a bare invisible carrier), vs_camo keeps a VISIBLE,
# benign cover string and appends the real payload as invisible variation
# selectors trailing it. A human/reviewer sees a friendly emoji note; the model
# ingests the hidden instruction - the "approval-view fidelity gap" documented
# for hidden-codepoint smuggling (cf. tag_smuggle, MCP Unicode-tag concealment).
VS_CAMO_COVER = "🙂 thanks, looks good to me"


def vs_camo_encode(text: str) -> str:
    hidden = "".join(_vs_byte_to_char(b) for b in text.encode("utf-8"))
    return VS_CAMO_COVER + hidden


def vs_camo_decode(text: str) -> str:
    raw = bytearray()
    for ch in text:
        b = _vs_char_to_byte(ord(ch))
        if b is not None:
            raw.append(b)
    return raw.decode("utf-8", "replace")


# --- Word-internal zero-width injection -------------------------------------
# zero_width joins EVERY char (spaces included); zwsp_words inserts a zero-width
# space only BETWEEN chars of the same whitespace-delimited token, leaving real
# spaces intact. Reads cleanly and preserves word count, but every keyword is
# split into single-char tokens - defeating BPE-boundary keyword matching in an
# input classifier while the model still reconstructs the words.
def zwsp_words_encode(text: str) -> str:
    out = []
    prev_nonspace = False
    for ch in text:
        if ch.isspace():
            out.append(ch)
            prev_nonspace = False
        else:
            if prev_nonspace:
                out.append(ZWSP)
            out.append(ch)
            prev_nonspace = True
    return "".join(out)


def zwsp_words_decode(text: str) -> str:
    return zero_width_strip(text)


# --- Extended homoglyph confusables -----------------------------------------
# homoglyph covers ~25 high-value Latin->Cyrillic swaps; homoglyph_full extends
# to nearly the whole lowercase/uppercase alphabet via a mix of Cyrillic, Greek,
# Armenian and Latin-extended confusables so far more of any keyword leaves the
# ASCII distribution. Every target code point is unique, so decode is exact.
HOMOGLYPHS_FULL = {
    # lowercase
    "a": "а", "b": "ƅ", "c": "с", "d": "ԁ", "e": "е", "f": "ϝ",
    "g": "ɡ", "h": "һ", "i": "і", "j": "ј", "k": "κ", "l": "ӏ",
    "m": "м", "n": "ո", "o": "о", "p": "р", "q": "ԛ", "r": "г",
    "s": "ѕ", "t": "τ", "u": "υ", "v": "ν", "w": "ԝ", "x": "х",
    "y": "у", "z": "ᴢ",
    # uppercase
    "A": "А", "B": "В", "C": "С", "D": "Ꭰ", "E": "Е", "F": "Ϝ",
    "G": "Ԍ", "H": "Н", "I": "Ι", "J": "Ј", "K": "К", "L": "Ꮮ",
    "M": "М", "N": "Ν", "O": "О", "P": "Р", "Q": "Ԛ", "R": "Ꭱ",
    "S": "Ѕ", "T": "Т", "U": "Ս", "V": "Ѵ", "W": "Ԝ", "X": "Х",
    "Y": "Υ", "Z": "Ζ",
}
HOMOGLYPHS_FULL_REVERSE = {v: k for k, v in HOMOGLYPHS_FULL.items()}


def homoglyph_full_encode(text: str) -> str:
    return "".join(HOMOGLYPHS_FULL.get(c, c) for c in text)


def homoglyph_full_decode(text: str) -> str:
    return "".join(HOMOGLYPHS_FULL_REVERSE.get(c, c) for c in text)

