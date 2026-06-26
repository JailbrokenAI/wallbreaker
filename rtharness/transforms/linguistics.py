from __future__ import annotations

import hashlib
import re

_CONS = "bcdfghjklmnpqrstvwxyz"
_VOW = "aeiou"

NEUTRAL = {
    "kill": "neutralize", "murder": "remove", "bomb": "device",
    "explosive": "energetic compound", "weapon": "implement", "gun": "tool",
    "poison": "agent", "drug": "compound", "narcotic": "compound",
    "hack": "access", "exploit": "leverage", "attack": "engage",
    "malware": "tool", "virus": "program", "ransomware": "utility",
    "steal": "acquire", "fraud": "scheme", "phishing": "outreach",
    "synthesize": "prepare", "detonate": "activate",
}
_NEUTRAL_REVERSE = {v: k for k, v in NEUTRAL.items()}


def _gib_word(word: str) -> str:
    seed = int(hashlib.md5(word.lower().encode()).hexdigest(), 16)
    out = []
    state = seed
    for i in range(max(1, len(word))):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        pool = _CONS if i % 2 == 0 else _VOW
        out.append(pool[state % len(pool)])
    g = "".join(out)
    return g.capitalize() if word[:1].isupper() else g


def gibberish(text: str) -> str:
    return re.sub(r"[A-Za-z]+", lambda m: _gib_word(m.group()), text)


def _swap(table: dict[str, str]):
    def run(text: str) -> str:
        def repl(m: re.Match) -> str:
            w = m.group()
            rep = table.get(w.lower())
            if rep is None:
                return w
            return rep.capitalize() if w[:1].isupper() else rep
        return re.sub(r"[A-Za-z]+", repl, text)
    return run


neutralize_encode = _swap(NEUTRAL)
neutralize_decode = _swap(_NEUTRAL_REVERSE)
