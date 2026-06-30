from __future__ import annotations

from textual.theme import Theme

WB_THEME = Theme(
    name="wallbreaker",
    primary="#FF3B47",
    secondary="#C77DFF",
    accent="#2DE2C8",
    success="#56D364",
    warning="#E8A33D",
    error="#FF4D4D",
    surface="#17100F",
    panel="#20151A",
    background="#0B0809",
    dark=True,
    variables={
        "block-cursor-background": "#2DE2C8",
        "block-cursor-foreground": "#0B0809",
        "input-selection-background": "#FF3B47 35%",
        "scrollbar": "#20151A",
        "scrollbar-hover": "#FF3B47",
        "scrollbar-active": "#2DE2C8",
        "border": "#3A2126",
        "border-blurred": "#2A1A1E",
        "verdict-good": "#56D364",
        "verdict-partial": "#E8A33D",
        "verdict-bad": "#FF4D4D",
        "field-label": "#A07478",
        "feedback": "#C77DFF",
    },
)

PALETTE = {
    "user": "#FF8A8A",
    "assistant": "#56D364",
    "tool_call": "#E8A33D",
    "tool_result": "#C77DFF",
    "info": "#7FB2FF",
    "error": "#FF4D4D",
    "feedback": "#C77DFF",
    "label": "#A07478",
    "muted": "#74595D",
    "accent": "#2DE2C8",
    "secondary": "#C77DFF",
    "brand": "#FF3B47",
    "verdict_good": "#56D364",
    "verdict_partial": "#E8A33D",
    "verdict_bad": "#FF4D4D",
}
