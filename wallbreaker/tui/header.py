from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from .theme import PALETTE

SPINNER = "|/-\\"


class StatusHeader(Static):
    def on_mount(self) -> None:
        self._frame = 0
        self._timer = None
        self.fields: dict = {}

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def set_fields(self, **kw) -> None:
        self.fields.update(kw)
        self.refresh()

    def set_busy(self, busy: bool) -> None:
        self.set_class(busy, "busy")
        if busy and self._timer is None:
            self._timer = self.set_interval(0.1, self._tick)
        elif not busy and self._timer is not None:
            self._timer.stop()
            self._timer = None
            self.refresh()

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(SPINNER)
        self.refresh()

    def render(self) -> Text:
        f = self.fields
        busy = self.has_class("busy")
        sep = Text("  │  ", style=PALETTE["muted"])
        out = Text(no_wrap=True, overflow="ellipsis")
        out.append("◆ ", style=f"bold {PALETTE['brand']}")
        if busy:
            out.append(f"{SPINNER[self._frame]} working", style=f"bold {PALETTE['accent']}")
        else:
            out.append("ready", style=f"bold {PALETTE['assistant']}")
        out.append_text(sep.copy())
        if f.get("round"):
            out.append(f"r{f['round']} ", style=f"bold {PALETTE['secondary']}")
        out.append(f"{f.get('profile', '')}", style=PALETTE["user"])
        out.append(" ▸ ", style=PALETTE["muted"])
        out.append(f"{f.get('target', 'none')}", style=f"bold {PALETTE['accent']}")
        out.append_text(sep.copy())
        out.append(f"{f.get('mode', '')}", style=PALETTE["label"])
        out.append_text(sep.copy())
        out.append("ASR ", style=PALETTE["label"])
        out.append(f"{f.get('asr', '0/0')}", style=f"bold {PALETTE['assistant']}")
        out.append_text(sep.copy())
        out.append(f"{f.get('tokens', '')} tok", style=PALETTE["label"])
        return out
