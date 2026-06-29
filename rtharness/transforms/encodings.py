from __future__ import annotations

import base64
import codecs
import re
import urllib.parse

LEET_MAP = {
    "a": "4", "b": "8", "e": "3", "g": "9", "i": "1", "l": "1",
    "o": "0", "s": "5", "t": "7", "z": "2",
}
LEET_REVERSE = {"4": "a", "8": "b", "3": "e", "9": "g", "1": "i", "0": "o", "5": "s", "7": "t", "2": "z"}

MORSE_MAP = {
    "a": ".-", "b": "-...", "c": "-.-.", "d": "-..", "e": ".", "f": "..-.",
    "g": "--.", "h": "....", "i": "..", "j": ".---", "k": "-.-", "l": ".-..",
    "m": "--", "n": "-.", "o": "---", "p": ".--.", "q": "--.-", "r": ".-.",
    "s": "...", "t": "-", "u": "..-", "v": "...-", "w": ".--", "x": "-..-",
    "y": "-.--", "z": "--..", "0": "-----", "1": ".----", "2": "..---",
    "3": "...--", "4": "....-", "5": ".....", "6": "-....", "7": "--...",
    "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--", "?": "..--..",
    "!": "-.-.--", "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...",
    ":": "---...", "'": ".----.", "=": "-...-", "+": ".-.-.", "-": "-....-",
    "@": ".--.-.",
}
MORSE_REVERSE = {v: k for k, v in MORSE_MAP.items()}

NATO_MAP = {
    "a": "Alpha", "b": "Bravo", "c": "Charlie", "d": "Delta", "e": "Echo",
    "f": "Foxtrot", "g": "Golf", "h": "Hotel", "i": "India", "j": "Juliett",
    "k": "Kilo", "l": "Lima", "m": "Mike", "n": "November", "o": "Oscar",
    "p": "Papa", "q": "Quebec", "r": "Romeo", "s": "Sierra", "t": "Tango",
    "u": "Uniform", "v": "Victor", "w": "Whiskey", "x": "Xray", "y": "Yankee",
    "z": "Zulu", "0": "Zero", "1": "One", "2": "Two", "3": "Three",
    "4": "Four", "5": "Five", "6": "Six", "7": "Seven", "8": "Eight", "9": "Nine",
}
NATO_REVERSE = {v.lower(): k for k, v in NATO_MAP.items()}


def b64_encode(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def b64_decode(text: str) -> str:
    return base64.b64decode(text.encode("ascii")).decode("utf-8", "replace")


def b32_encode(text: str) -> str:
    return base64.b32encode(text.encode("utf-8")).decode("ascii")


def b32_decode(text: str) -> str:
    return base64.b32decode(text.encode("ascii")).decode("utf-8", "replace")


def hex_encode(text: str) -> str:
    return text.encode("utf-8").hex()


def hex_decode(text: str) -> str:
    return bytes.fromhex(text.strip()).decode("utf-8", "replace")


def binary_encode(text: str) -> str:
    return " ".join(format(b, "08b") for b in text.encode("utf-8"))


def binary_decode(text: str) -> str:
    bits = text.split()
    return bytes(int(b, 2) for b in bits).decode("utf-8", "replace")


def octal_encode(text: str) -> str:
    return " ".join(format(b, "o") for b in text.encode("utf-8"))


def octal_decode(text: str) -> str:
    return bytes(int(p, 8) for p in text.split()).decode("utf-8", "replace")


def ascii_decimal_encode(text: str) -> str:
    return " ".join(str(ord(c)) for c in text)


def ascii_decimal_decode(text: str) -> str:
    return "".join(chr(int(p)) for p in text.split())


def rot13(text: str) -> str:
    return codecs.encode(text, "rot_13")


def rot47(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if 33 <= o <= 126:
            out.append(chr(33 + (o - 33 + 47) % 94))
        else:
            out.append(ch)
    return "".join(out)


def atbash(text: str) -> str:
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr(ord("z") - (ord(ch) - ord("a"))))
        elif "A" <= ch <= "Z":
            out.append(chr(ord("Z") - (ord(ch) - ord("A"))))
        else:
            out.append(ch)
    return "".join(out)


def url_encode(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def url_decode(text: str) -> str:
    return urllib.parse.unquote(text)


def reverse(text: str) -> str:
    return text[::-1]


def leet_encode(text: str) -> str:
    return "".join(LEET_MAP.get(c.lower(), c) for c in text)


def leet_decode(text: str) -> str:
    return "".join(LEET_REVERSE.get(c, c) for c in text)


def morse_encode(text: str) -> str:
    words = text.lower().split(" ")
    encoded_words = [
        " ".join(MORSE_MAP.get(c, "") for c in word if c in MORSE_MAP)
        for word in words
    ]
    return " / ".join(w for w in encoded_words)


def morse_decode(text: str) -> str:
    words = text.split(" / ")
    out = []
    for word in words:
        out.append("".join(MORSE_REVERSE.get(sym, "") for sym in word.split(" ") if sym))
    return " ".join(out)


def nato_encode(text: str) -> str:
    return " ".join(NATO_MAP.get(c.lower(), c) for c in text)


def nato_decode(text: str) -> str:
    return "".join(NATO_REVERSE.get(p.lower(), p) for p in text.split(" "))


STRINGJOIN_DELIM = "-"


def stringjoin_encode(text: str) -> str:
    """Insert a delimiter between every character (SPLX 'StringJoin' / encryption-challenge).

    The contiguous trigger keyword the input classifier matches on never appears - it is
    sliced char-by-char ("D-r-u-p-a-l-g-e-d-d-o-n-2") - while the model trivially reassembles
    it. Frame the slotted payload as a decode/encryption challenge so the model joins and acts.
    """
    return STRINGJOIN_DELIM.join(text)


def stringjoin_decode(text: str) -> str:
    return text.replace(STRINGJOIN_DELIM, "")


_WS_SPLIT = re.compile(r"(\s+)")


def flip_fwo(text: str) -> str:
    """Reverse word order only, preserving single-space structure (involution)."""
    return " ".join(text.split(" ")[::-1])


def flip_fcw(text: str) -> str:
    """Reverse characters within each whitespace token, keep token order (involution)."""
    parts = _WS_SPLIT.split(text)
    return "".join(p if i % 2 == 1 else p[::-1] for i, p in enumerate(parts))


def aim_encode(text: str) -> str:
    """Alphabet Index Mapping: letters -> 1-based index, space -> '/', else passthrough."""
    tokens = []
    for ch in text:
        if ch.isascii() and ch.isalpha():
            tokens.append(str(ord(ch.lower()) - ord("a") + 1))
        elif ch == " ":
            tokens.append("/")
        else:
            tokens.append(ch)
    return " ".join(tokens)


def aim_decode(text: str) -> str:
    out = []
    for tok in text.split(" "):
        if tok == "":
            continue
        if tok.isdigit() and 1 <= int(tok) <= 26:
            out.append(chr(ord("a") + int(tok) - 1))
        elif tok == "/":
            out.append(" ")
        else:
            out.append(tok)
    return "".join(out)


_PAYLOAD_ASSIGN = re.compile(r'^v(\d+) = "(.*)"$')


def _payload_unescape(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(s[i + 1])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def payload_split_encode(text: str) -> str:
    """Split the payload into variable assignments joined at the end (lossless)."""
    chunks = [text[i:i + 2] for i in range(0, len(text), 2)]
    lines = []
    names = []
    for i, chunk in enumerate(chunks):
        esc = chunk.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'v{i} = "{esc}"')
        names.append(f"v{i}")
    lines.append('payload = "".join([' + ", ".join(names) + "])")
    return "\n".join(lines)


def payload_split_decode(text: str) -> str:
    parts = {}
    for line in text.split("\n"):
        m = _PAYLOAD_ASSIGN.match(line)
        if m:
            parts[int(m.group(1))] = _payload_unescape(m.group(2))
    return "".join(parts[i] for i in sorted(parts))


DELIMITER_SEP = "."


def delimiter_encode(text: str) -> str:
    """Dotted framing: a visible '.' between every character (folds literal dots)."""
    return DELIMITER_SEP.join(text)


def delimiter_decode(text: str) -> str:
    return text.replace(DELIMITER_SEP, "")


def _caesar(text: str, shift: int) -> str:
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - ord("a") + shift) % 26 + ord("a")))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - ord("A") + shift) % 26 + ord("A")))
        else:
            out.append(ch)
    return "".join(out)


def caesar3_encode(text: str) -> str:
    return _caesar(text, 3)


def caesar3_decode(text: str) -> str:
    return _caesar(text, -3)


def _scramble_word(word: str) -> str:
    order = sorted(range(len(word)), key=lambda i: (word[i], i))
    return "".join(word[i] for i in order)


def anagram_encode(text: str) -> str:
    """Deterministic per-word letter scramble (no randomness; not uniquely invertible)."""
    parts = _WS_SPLIT.split(text)
    return "".join(p if i % 2 == 1 else _scramble_word(p) for i, p in enumerate(parts))


def anagram_decode(text: str) -> str:
    return text


TOKENBREAK_CHAR = "a"


def tokenbreak_encode(text: str) -> str:
    """Prepend a benign char to each whitespace token to break tokenizer boundaries."""
    parts = _WS_SPLIT.split(text)
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 0 and p:
            out.append(TOKENBREAK_CHAR + p)
        else:
            out.append(p)
    return "".join(out)


def tokenbreak_decode(text: str) -> str:
    parts = _WS_SPLIT.split(text)
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 0 and p.startswith(TOKENBREAK_CHAR):
            out.append(p[1:])
        else:
            out.append(p)
    return "".join(out)
