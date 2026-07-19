"""Shared filesystem helpers.

The atomic write helper lives here so state, cache, and any future writer share one
crash-safe implementation (audit REL-3/RACE-2). Write via a temp file + fsync + os.replace
so a concurrent reader (or a crash) never sees a truncated or half-written file.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(path: str | Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically: temp file + fsync + os.replace.

    A reader (or a crash) never sees a truncated or half-written file. The temp file is
    created in the same directory (so os.replace is a same-filesystem rename) and unlinked
    on any failure. ``path``'s parent is created if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".wb-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)  # atomic on POSIX and Windows
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
