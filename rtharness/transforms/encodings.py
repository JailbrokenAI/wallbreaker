from __future__ import annotations

import base64
import codecs
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
