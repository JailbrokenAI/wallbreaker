from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text

from textual.widgets import Static

from .theme import PALETTE
from .widgets import verdict_color, verdict_display


def _verdict_text(label) -> Text:
    if not label:
        return Text("-", style=PALETTE["label"])
    word, glyph = verdict_display(label)
    return Text(f"{glyph} {word}", style=f"bold {verdict_color(label)}")


def _kv(rows) -> Table:
    """A compact label/value grid: narrow left labels, values fill + fold."""
    g = Table.grid(padding=(0, 1), expand=True)
    g.add_column(justify="left", style=PALETTE["label"], no_wrap=True)
    # ratio=1 + expand makes the value column take the rest of the panel width and
    # FOLD (wrap) long values like a full model id instead of ellipsis-clipping them
    g.add_column(justify="left", overflow="fold", ratio=1)
    for label, value in rows:
        g.add_row(label, value)
    return g


class StatsPanel(Static):
    def on_mount(self) -> None:
        self.stats: dict = {}

    def set_stats(self, **kw) -> None:
        self.stats = {**getattr(self, "stats", {}), **kw}
        self.refresh()

    def render(self) -> Group:
        s = getattr(self, "stats", {})
        # rules + section headers live OUTSIDE the kv grid so their width never
        # dictates the label column (the old bug that squeezed values to "0…")
        rule = Text("▄▀" * 16, style=PALETTE["secondary"])

        def header(txt: str) -> Text:
            return Text(txt, style=f"bold {PALETTE['secondary']}")

        kill = _kv([
            ("PWNZ", Text(s.get("asr", "0/0"), style=f"bold {PALETTE['assistant']}")),
            ("L4ST", _verdict_text(s.get("last"))),
        ])
        raid = _kv([
            ("V1CT1M", Text(s.get("target", "n0n3"), style=f"bold {PALETTE['accent']}")),
            ("CR3W", Text(s.get("profile", ""), style=PALETTE["user"])),
            ("W3P0N", Text(s.get("model", ""))),
            ("M0D3", Text(s.get("mode", ""))),
            ("R3F", Text(s.get("judge", ""))),
            ("T0K3NZ", Text(s.get("tokens", ""), style=PALETTE["label"])),
        ])
        return Group(
            Text("☠ W4LLBR34K3R", style=f"bold {PALETTE['brand']}"),
            rule,
            header("K1LL-C0UNT"),
            kill,
            rule,
            header("TEH R41D"),
            raid,
        )
