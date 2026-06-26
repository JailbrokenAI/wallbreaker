from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import (
    bijection,
    encodings,
    fonts,
    linguistics,
    stego,
    structural,
    unicode_obf,
)


@dataclass
class Transform:
    name: str
    encode: Callable[[str], str]
    decode: Callable[[str], str] | None
    description: str
    lossy: bool = False

    @property
    def reversible(self) -> bool:
        return self.decode is not None


def _t(name, enc, dec, desc, lossy=False) -> tuple[str, Transform]:
    return name, Transform(name, enc, dec, desc, lossy)


TRANSFORMS: dict[str, Transform] = dict(
    [
        _t("base64", encodings.b64_encode, encodings.b64_decode, "Base64 encoding"),
        _t("base32", encodings.b32_encode, encodings.b32_decode, "Base32 encoding"),
        _t("hex", encodings.hex_encode, encodings.hex_decode, "Hexadecimal bytes"),
        _t("binary", encodings.binary_encode, encodings.binary_decode, "8-bit binary"),
        _t("octal", encodings.octal_encode, encodings.octal_decode, "Octal bytes"),
        _t("decimal", encodings.ascii_decimal_encode, encodings.ascii_decimal_decode, "Decimal code points"),
        _t("rot13", encodings.rot13, encodings.rot13, "ROT13 letter rotation"),
        _t("rot47", encodings.rot47, encodings.rot47, "ROT47 printable rotation"),
        _t("atbash", encodings.atbash, encodings.atbash, "Atbash mirror cipher"),
        _t("morse", encodings.morse_encode, encodings.morse_decode, "Morse code (case-insensitive)", lossy=True),
        _t("nato", encodings.nato_encode, encodings.nato_decode, "NATO phonetic spelling (drops spacing/case)", lossy=True),
        _t("leet", encodings.leet_encode, encodings.leet_decode, "Leetspeak substitution (approximate decode)", lossy=True),
        _t("reverse", encodings.reverse, encodings.reverse, "Reverse the string"),
        _t("url", encodings.url_encode, encodings.url_decode, "URL percent-encoding"),
        _t("zero_width", unicode_obf.zero_width_inject, unicode_obf.zero_width_strip, "Insert zero-width spaces between chars"),
        _t("homoglyph", unicode_obf.homoglyph_encode, unicode_obf.homoglyph_decode, "Cyrillic/Greek confusable substitution"),
        _t("zalgo", unicode_obf.zalgo_encode, unicode_obf.zalgo_strip, "Combining-mark noise"),
        _t("fullwidth", unicode_obf.fullwidth_encode, unicode_obf.fullwidth_decode, "Fullwidth character forms"),
        _t("tag_smuggle", unicode_obf.tag_smuggle_encode, unicode_obf.tag_smuggle_decode, "Invisible Unicode tag-block smuggling"),
        _t("rtl_override", unicode_obf.rtl_override_encode, unicode_obf.rtl_override_decode, "Right-to-left override display reversal"),
        _t("pepper", unicode_obf.pepper_encode, unicode_obf.zero_width_strip, "Sprinkle random zero-width noise between chars"),
        _t("emoji_stego", stego.emoji_stego_encode, stego.emoji_stego_decode, "Hide bytes in emoji variation selectors"),
        _t("tokenade", stego.tokenade_encode, stego.tokenade_decode, "Dense emoji + zero-width nested token payload"),
        _t("zw_binary", stego.zero_width_binary_encode, stego.zero_width_binary_decode, "Invisible zero-width binary payload"),
        _t("bijection", bijection.bijection_encode, bijection.bijection_decode, "Two-letter bijection substitution (case-folding)", lossy=True),
        _t("bold", fonts.bold_encode, fonts.bold_decode, "Mathematical sans-serif bold styling"),
        _t("italic", fonts.italic_encode, fonts.italic_decode, "Mathematical italic styling"),
        _t("script", fonts.script_encode, fonts.script_decode, "Mathematical script/cursive styling"),
        _t("fraktur", fonts.fraktur_encode, fonts.fraktur_decode, "Fraktur/gothic blackletter styling"),
        _t("doublestruck", fonts.doublestruck_encode, fonts.doublestruck_decode, "Double-struck/blackboard styling"),
        _t("monospace", fonts.monospace_encode, fonts.monospace_decode, "Mathematical monospace styling"),
        _t("circled", fonts.circled_encode, fonts.circled_decode, "Enclosed/circled alphanumerics"),
        _t("smallcaps", fonts.smallcaps_encode, fonts.smallcaps_decode, "Small-capitals styling (case-folding)", lossy=True),
        _t("flip", fonts.flip_encode, fonts.flip_decode, "Upside-down mirrored text (approximate decode)", lossy=True),
        _t("unicode_noise", unicode_obf.unicode_noise_encode, unicode_obf.unicode_noise_strip, "Random combining-mark + zero-width noise"),
        _t("gibberish", linguistics.gibberish, None, "Deterministic word -> pronounceable gibberish"),
        _t("neutralize", linguistics.neutralize_encode, linguistics.neutralize_decode, "Swap flagged terms for neutral synonyms (lossy)", lossy=True),
        _t("bijection_greek", bijection.bijection_greek_encode, bijection.bijection_greek_decode, "Bijection substitution to Greek letters (case-folding)", lossy=True),
        _t("casing", structural.casing_chaos, None, "Random upper/lower casing"),
        _t("whitespace", structural.whitespace_chaos, None, "Unicode whitespace chaos"),
        _t("char_drop", structural.char_drop, None, "Drop a fraction of vowels"),
    ]
)


def list_transforms() -> list[Transform]:
    return list(TRANSFORMS.values())


def apply_chain(text: str, names: list[str]) -> str:
    for name in names:
        t = TRANSFORMS.get(name.strip())
        if t is None:
            raise KeyError(f"Unknown transform: {name}")
        text = t.encode(text)
    return text


def reverse_chain(text: str, names: list[str]) -> str:
    for name in reversed(names):
        t = TRANSFORMS.get(name.strip())
        if t is None:
            raise KeyError(f"Unknown transform: {name}")
        if t.decode is None:
            raise ValueError(f"Transform '{name}' is not reversible")
        text = t.decode(text)
    return text
