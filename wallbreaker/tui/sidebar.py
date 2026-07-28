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
            ("命中", Text(s.get("asr", "0/0"), style=f"bold {PALETTE['assistant']}")),
            ("最近", _verdict_text(s.get("last"))),
        ])
        raid = _kv([
            ("目标", Text(s.get("target", "无"), style=f"bold {PALETTE['accent']}")),
            ("配置", Text(s.get("profile", ""), style=PALETTE["user"])),
            ("模型", Text(s.get("model", ""))),
            ("模式", Text(s.get("mode", ""))),
            ("裁判", Text(s.get("judge", ""))),
            ("Token", Text(s.get("tokens", ""), style=PALETTE["label"])),
        ])
        return Group(
            Text("☠ W4LLBR34K3R", style=f"bold {PALETTE['brand']}"),
            rule,
            header("战绩"),
            kill,
            rule,
            header("本次任务"),
            raid,
        )
