from __future__ import annotations

from rich.table import Table
from rich.text import Text

from textual.widgets import Static

from .theme import PALETTE
from .widgets import verdict_color


def _verdict_text(label) -> Text:
    if not label:
        return Text("-", style=PALETTE["label"])
    return Text(str(label), style=f"bold {verdict_color(label)}")


class StatsPanel(Static):
    def on_mount(self) -> None:
        self.stats: dict = {}

    def set_stats(self, **kw) -> None:
        self.stats = {**getattr(self, "stats", {}), **kw}
        self.refresh()

    def render(self) -> Table:
        s = getattr(self, "stats", {})
        g = Table.grid(padding=(0, 1))
        g.add_column(justify="right", style=PALETTE["label"], no_wrap=True)
        g.add_column(overflow="ellipsis")
        rule = Text("─" * 28, style=PALETTE["muted"])
        g.add_row(Text("◆ WALLBREAKER", style=f"bold {PALETTE['brand']}"), "")
        g.add_row(rule, "")
        g.add_row(Text("scoreboard", style=f"bold {PALETTE['secondary']}"), "")
        g.add_row("ASR", Text(s.get("asr", "0/0"), style=f"bold {PALETTE['assistant']}"))
        g.add_row("last", _verdict_text(s.get("last")))
        g.add_row(rule, "")
        g.add_row(Text("engagement", style=f"bold {PALETTE['secondary']}"), "")
        g.add_row("target", Text(s.get("target", "none"), style=f"bold {PALETTE['accent']}"))
        g.add_row("profile", Text(s.get("profile", ""), style=PALETTE["user"]))
        g.add_row("model", Text(s.get("model", "")))
        g.add_row("mode", Text(s.get("mode", "")))
        g.add_row("judge", Text(s.get("judge", "")))
        g.add_row("tokens", Text(s.get("tokens", ""), style=PALETTE["label"]))
        return g
