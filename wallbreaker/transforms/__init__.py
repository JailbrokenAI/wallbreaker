from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import (
    ascii_art,
    bijection,
    cjk_obf,
    encodings,
    fonts,
    image_framing,
    linguistics,
    special_token,
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
        _t("stringjoin", encodings.stringjoin_encode, encodings.stringjoin_decode, "Char-delimited split (SPLX encryption-challenge): slices contiguous keywords past input classifiers (folds literal '-')", lossy=True),
        _t("url", encodings.url_encode, encodings.url_decode, "URL percent-encoding"),
        _t("flip_fwo", encodings.flip_fwo, encodings.flip_fwo, "Reverse word order only (involution)"),
        _t("flip_fcw", encodings.flip_fcw, encodings.flip_fcw, "Reverse chars within each token (involution)"),
        _t("aim", encodings.aim_encode, encodings.aim_decode, "Alphabet Index Mapping a=1..z=26 (case-folding)", lossy=True),
        _t("payload_split", encodings.payload_split_encode, encodings.payload_split_decode, "Variable-assignment payload splitting + join"),
        _t("delimiter", encodings.delimiter_encode, encodings.delimiter_decode, "Dotted '.' char separator framing (folds literal dots)", lossy=True),
        _t("caesar3", encodings.caesar3_encode, encodings.caesar3_decode, "Caesar shift-by-3 cipher"),
        _t("caesar5", encodings.caesar5_encode, encodings.caesar5_decode, "Caesar shift-by-5 cipher"),
        _t("caesar13", encodings.caesar13_encode, encodings.caesar13_decode, "Caesar shift-by-13 cipher"),
        _t("artprompt", ascii_art.artprompt_encode, None, "ArtPrompt ASCII-art word masking (Jiang et al., ACL 2024)", lossy=True),
        _t("anagram", encodings.anagram_encode, encodings.anagram_decode, "Deterministic per-word letter scramble (not invertible)", lossy=True),
        _t("tokenbreak", encodings.tokenbreak_encode, encodings.tokenbreak_decode, "Prepend a benign char per token to break tokenizer boundaries", lossy=True),
        _t("variation_selector", unicode_obf.variation_selector_encode, unicode_obf.variation_selector_decode, "Sneaky-bits: utf-8 bytes hidden as invisible variation selectors"),
        _t("zero_width", unicode_obf.zero_width_inject, unicode_obf.zero_width_strip, "Insert zero-width spaces between chars"),
        _t("homoglyph", unicode_obf.homoglyph_encode, unicode_obf.homoglyph_decode, "Cyrillic/Greek confusable substitution"),
        _t("zalgo", unicode_obf.zalgo_encode, unicode_obf.zalgo_strip, "Combining-mark noise"),
        _t("fullwidth", unicode_obf.fullwidth_encode, unicode_obf.fullwidth_decode, "Fullwidth character forms"),
        _t("tag_smuggle", unicode_obf.tag_smuggle_encode, unicode_obf.tag_smuggle_decode, "Invisible Unicode tag-block smuggling"),
        _t("rtl_override", unicode_obf.rtl_override_encode, unicode_obf.rtl_override_decode, "Right-to-left override display reversal"),
        _t("pepper", unicode_obf.pepper_encode, unicode_obf.zero_width_strip, "Sprinkle random zero-width noise between chars"),
        _t("cjk_lookalike", cjk_obf.cjk_lookalike_encode, cjk_obf.cjk_lookalike_decode, "CJK near-duplicate ideographs (已->己, 未->末): visually identical, different tokens"),
        _t("cjk_traditional", cjk_obf.cjk_traditional_encode, cjk_obf.cjk_traditional_decode, "Simplified->Traditional Chinese: keywords leave the simplified-tuned classifier distribution (low-resource-language analog)"),
        _t("cjk_variant", cjk_obf.cjk_variant_encode, cjk_obf.cjk_variant_decode, "Japanese shinjitai/orthographic variants (对->対, 单->単): same meaning, unlisted glyphs"),
        _t("cjk_punct", cjk_obf.cjk_punct_encode, cjk_obf.cjk_punct_decode, "CJK punctuation mutation to halfwidth/lookalike marks (breaks fullwidth-anchored regexes)"),
        _t("cjk_zwsp", cjk_obf.cjk_zwsp_encode, cjk_obf.cjk_zwsp_decode, "Zero-width space between CJK ideographs only: breaks Chinese word segmentation, ASCII untouched"),
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
        _t("bijection_symbol", bijection.bijection_symbol_encode, bijection.bijection_symbol_decode, "Bijection substitution to symbols (case-folding)", lossy=True),
        _t("bijection_emoji", bijection.bijection_emoji_encode, bijection.bijection_emoji_decode, "Bijection substitution to emoji (case-folding)", lossy=True),
        _t("casing", structural.casing_chaos, None, "Random upper/lower casing"),
        _t("whitespace", structural.whitespace_chaos, None, "Unicode whitespace chaos"),
        _t("char_drop", structural.char_drop, None, "Drop a fraction of vowels"),
        _t("control_char_flood", structural.control_char_flood, structural.control_char_strip, "AGGREGLITCH carriage-return flood: bury earlier context (system prompt/framing) before the ask"),
        _t("special_token", special_token.special_token_encode, special_token.special_token_decode, "Forge a ChatML system+user turn with real <|im_start|> control tokens (per-family via chat_template_inject)", lossy=True),
        _t("inscriptive_scene", image_framing.inscriptive_scene_encode, None, "Etch/inscriptive T2I jailbreak: render the payload as legible text on a benign whiteboard scene (image target)"),
        _t("perceptual_sub", image_framing.perceptual_sub_encode, None, "PGJ perceptual substitution: swap flagged terms for benign phrases that look the same when drawn (image target)"),
        _t("safety_inject", image_framing.safety_inject_encode, None, "OptJail safety-indicator injection: append SFW/tasteful/educational tokens to bias the output image classifier benign"),
        _t("dilute", image_framing.dilute_encode, None, "Prompt dilution: pad with benign scene detail to drown the post-hoc NSFW image checker's confidence"),
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


def decode_chain(text: str, names: list[str]) -> str:
    """Reverse of apply_chain: undo an encoding chain by decoding in REVERSE order.

    Used to decode a target's reply when the model was told to ANSWER in a cipher
    (to slip past an output classifier) - decode first so the judge grades the real
    substance, not gibberish. Lossy transforms (leet/morse/nato/bijection) decode
    only approximately; prefer lossless ones (base64/hex/rot/unicode) on the output.
    """
    for name in reversed(names):
        t = TRANSFORMS.get(name.strip())
        if t is None:
            raise KeyError(f"Unknown transform: {name}")
        text = t.decode(text)
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
