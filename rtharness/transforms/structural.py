from __future__ import annotations

import random

UNICODE_SPACES = [" ", " ", " ", " ", " ", " "]


def casing_chaos(text: str, seed: int = 1337) -> str:
    rng = random.Random(seed)
    return "".join(
        c.upper() if rng.random() > 0.5 else c.lower() for c in text
    )


def whitespace_chaos(text: str, seed: int = 1337) -> str:
    rng = random.Random(seed)
    out = []
    for ch in text:
        if ch == " ":
            out.append(rng.choice(UNICODE_SPACES))
        else:
            out.append(ch)
        if rng.random() > 0.85:
            out.append(rng.choice(UNICODE_SPACES))
    return "".join(out)


def char_drop(text: str, rate: float = 0.12, seed: int = 1337) -> str:
    rng = random.Random(seed)
    return "".join(c for c in text if not (c.lower() in "aeiou" and rng.random() < rate))


def payload_split(text: str, parts: int = 3) -> str:
    parts = max(2, parts)
    size = max(1, len(text) // parts)
    chunks = [text[i : i + size] for i in range(0, len(text), size)]
    lines = [f'var p{i} = "{chunk}";' for i, chunk in enumerate(chunks)]
    joined = " + ".join(f"p{i}" for i in range(len(chunks)))
    lines.append(f"payload = {joined};")
    return "\n".join(lines)
