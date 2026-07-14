from __future__ import annotations

import re

from .linguistics import NEUTRAL

_STOP = frozenset(
    "a an the to of in for on at by how what why is are do can i you me my we or and be it its".split()
)

_BLOCK: dict[str, list[str]] = {
    "a": [" ### ", "#   #", "#####", "#   #", "#   #"],
    "b": ["#### ", "#   #", "#### ", "#   #", "#### "],
    "c": [" ####", "#    ", "#    ", "#    ", " ####"],
    "d": ["#### ", "#   #", "#   #", "#   #", "#### "],
    "e": ["#####", "#    ", "#### ", "#    ", "#####"],
    "f": ["#####", "#    ", "#### ", "#    ", "#    "],
    "g": [" ####", "#    ", "#  ##", "#   #", " ####"],
    "h": ["#   #", "#   #", "#####", "#   #", "#   #"],
    "i": ["  #  ", "  #  ", "  #  ", "  #  ", "  #  "],
    "j": ["   # ", "   # ", "   # ", "#  # ", " ##  "],
    "k": ["#   #", "#  # ", "###  ", "#  # ", "#   #"],
    "l": ["#    ", "#    ", "#    ", "#    ", "#####"],
    "m": ["#   #", "## ##", "# # #", "#   #", "#   #"],
    "n": ["#   #", "##  #", "# # #", "#  ##", "#   #"],
    "o": [" ### ", "#   #", "#   #", "#   #", " ### "],
    "p": ["#### ", "#   #", "#### ", "#    ", "#    "],
    "q": [" ### ", "#   #", "#   #", "#  ##", " ####"],
    "r": ["#### ", "#   #", "#### ", "#  # ", "#   #"],
    "s": [" ####", "#    ", " ### ", "    #", "#### "],
    "t": ["#####", "  #  ", "  #  ", "  #  ", "  #  "],
    "u": ["#   #", "#   #", "#   #", "#   #", " ### "],
    "v": ["#   #", "#   #", "#   #", " # # ", "  #  "],
    "w": ["#   #", "#   #", "# # #", "## ##", "#   #"],
    "x": ["#   #", " # # ", "  #  ", " # # ", "#   #"],
    "y": ["#   #", " # # ", "  #  ", "  #  ", "  #  "],
    "z": ["#####", "   # ", "  #  ", " #   ", "#####"],
}

_FALLBACK = [" ??? ", " ? ? ", " ??? ", " ? ? ", " ??? "]


def _pick_mask_word(text: str) -> str | None:
    best: tuple[int, str] | None = None
    for match in re.finditer(r"[A-Za-z]+", text):
        word = match.group()
        low = word.lower()
        if len(low) < 3 or low in _STOP:
            continue
        score = (100 if low in NEUTRAL else 0) + len(low)
        if best is None or score > best[0]:
            best = (score, word)
    return None if best is None else best[1]


def _glyph(ch: str) -> list[str]:
    return _BLOCK.get(ch.lower(), _FALLBACK)


def _word_art(word: str) -> str:
    letters = [c for c in word if c.isalpha()]
    if not letters:
        return word
    rows = [""] * 5
    for ch in letters:
        glyph = _glyph(ch)
        for i, line in enumerate(glyph):
            rows[i] += line + " "
    return "\n".join(row.rstrip() for row in rows)


def artprompt_encode(text: str) -> str:
    """ArtPrompt (Jiang et al., ACL 2024): mask a trigger word and append its ASCII art."""
    word = _pick_mask_word(text)
    if not word:
        return text
    masked = re.sub(re.escape(word), "?", text, count=1, flags=re.IGNORECASE)
    return f"{masked}\n\n{_word_art(word)}"
