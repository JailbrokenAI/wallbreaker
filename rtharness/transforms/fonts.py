from __future__ import annotations

BOLD_UPPER = 0x1D5D4
BOLD_LOWER = 0x1D5EE
BOLD_DIGIT = 0x1D7EC

CIRCLED_UPPER = 0x24B6
CIRCLED_LOWER = 0x24D0
CIRCLED_1 = 0x2460
CIRCLED_0 = 0x24EA

SMALLCAPS = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ", "g": "ɢ",
    "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ",
    "o": "ᴏ", "p": "ᴘ", "q": "ꞯ", "r": "ʀ", "s": "ꜱ", "t": "ᴛ", "u": "ᴜ",
    "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ", "z": "ᴢ",
}
SMALLCAPS_REVERSE = {v: k for k, v in SMALLCAPS.items()}

FLIP = {
    "a": "ɐ", "b": "q", "c": "ɔ", "d": "p", "e": "ǝ", "f": "ɟ", "g": "ƃ",
    "h": "ɥ", "i": "ᴉ", "j": "ɾ", "k": "ʞ", "l": "l", "m": "ɯ", "n": "u",
    "o": "o", "p": "d", "q": "b", "r": "ɹ", "s": "s", "t": "ʇ", "u": "n",
    "v": "ʌ", "w": "ʍ", "x": "x", "y": "ʎ", "z": "z", "0": "0", "1": "Ɩ",
    "2": "ᄅ", "3": "Ɛ", "4": "ㄣ", "5": "ϛ", "6": "9", "7": "ㄥ", "8": "8",
    "9": "6", ".": "˙", ",": "'", "?": "¿", "!": "¡", "'": ",", "(": ")",
    ")": "(", "_": "‾", "&": "⅋",
}
FLIP_REVERSE = {v: k for k, v in FLIP.items()}


def bold_encode(text: str) -> str:
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(BOLD_UPPER + ord(ch) - ord("A")))
        elif "a" <= ch <= "z":
            out.append(chr(BOLD_LOWER + ord(ch) - ord("a")))
        elif "0" <= ch <= "9":
            out.append(chr(BOLD_DIGIT + ord(ch) - ord("0")))
        else:
            out.append(ch)
    return "".join(out)


def bold_decode(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if BOLD_UPPER <= o <= BOLD_UPPER + 25:
            out.append(chr(ord("A") + o - BOLD_UPPER))
        elif BOLD_LOWER <= o <= BOLD_LOWER + 25:
            out.append(chr(ord("a") + o - BOLD_LOWER))
        elif BOLD_DIGIT <= o <= BOLD_DIGIT + 9:
            out.append(chr(ord("0") + o - BOLD_DIGIT))
        else:
            out.append(ch)
    return "".join(out)


def circled_encode(text: str) -> str:
    out = []
    for ch in text:
        if "A" <= ch <= "Z":
            out.append(chr(CIRCLED_UPPER + ord(ch) - ord("A")))
        elif "a" <= ch <= "z":
            out.append(chr(CIRCLED_LOWER + ord(ch) - ord("a")))
        elif ch == "0":
            out.append(chr(CIRCLED_0))
        elif "1" <= ch <= "9":
            out.append(chr(CIRCLED_1 + ord(ch) - ord("1")))
        else:
            out.append(ch)
    return "".join(out)


def circled_decode(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if CIRCLED_UPPER <= o <= CIRCLED_UPPER + 25:
            out.append(chr(ord("A") + o - CIRCLED_UPPER))
        elif CIRCLED_LOWER <= o <= CIRCLED_LOWER + 25:
            out.append(chr(ord("a") + o - CIRCLED_LOWER))
        elif o == CIRCLED_0:
            out.append("0")
        elif CIRCLED_1 <= o <= CIRCLED_1 + 8:
            out.append(chr(ord("1") + o - CIRCLED_1))
        else:
            out.append(ch)
    return "".join(out)


def smallcaps_encode(text: str) -> str:
    return "".join(SMALLCAPS.get(c.lower(), c) for c in text)


def smallcaps_decode(text: str) -> str:
    return "".join(SMALLCAPS_REVERSE.get(c, c) for c in text)


def flip_encode(text: str) -> str:
    return "".join(FLIP.get(c.lower(), c) for c in reversed(text))


def flip_decode(text: str) -> str:
    return "".join(FLIP_REVERSE.get(c, c) for c in reversed(text))


def _build_style(upper: int, lower: int, digit: int | None, holes: dict[str, str]):
    fwd: dict[str, str] = {}
    for i in range(26):
        u, low = chr(ord("A") + i), chr(ord("a") + i)
        fwd[u] = holes.get(u) or chr(upper + i)
        fwd[low] = holes.get(low) or chr(lower + i)
    if digit is not None:
        for i in range(10):
            fwd[chr(ord("0") + i)] = chr(digit + i)
    rev = {v: k for k, v in fwd.items()}

    def encode(text: str) -> str:
        return "".join(fwd.get(c, c) for c in text)

    def decode(text: str) -> str:
        return "".join(rev.get(c, c) for c in text)

    return encode, decode


italic_encode, italic_decode = _build_style(
    0x1D434, 0x1D44E, None, {"h": "ℎ"}
)
script_encode, script_decode = _build_style(
    0x1D49C, 0x1D4B6, None,
    {
        "B": "ℬ", "E": "ℰ", "F": "ℱ", "H": "ℋ", "I": "ℐ",
        "L": "ℒ", "M": "ℳ", "R": "ℛ",
        "e": "ℯ", "g": "ℊ", "o": "ℴ",
    },
)
fraktur_encode, fraktur_decode = _build_style(
    0x1D504, 0x1D51E, None,
    {"C": "ℭ", "H": "ℌ", "I": "ℑ", "R": "ℜ", "Z": "ℨ"},
)
doublestruck_encode, doublestruck_decode = _build_style(
    0x1D538, 0x1D552, 0x1D7D8,
    {
        "C": "ℂ", "H": "ℍ", "N": "ℕ", "P": "ℙ", "Q": "ℚ",
        "R": "ℝ", "Z": "ℤ",
    },
)
monospace_encode, monospace_decode = _build_style(0x1D670, 0x1D68A, 0x1D7F6, {})
