"""Shared styling for generated PNG cards (rank card, server wrapped).

Bundles Inter (SIL Open Font License, see bot/assets/fonts/Inter-OFL.txt)
so rendering doesn't depend on whatever fonts happen to be installed on
the host machine, this needs to work the same on a bare Ubuntu server
or someone's Windows desktop. Colors mirror the dashboard's CSS
variables so a generated card and the dashboard feel like the same
product.
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

FONT_PATH = Path(__file__).resolve().parent / "assets" / "fonts" / "Inter.ttf"

CARD_COLOR = (18, 21, 31)        # matches the dashboard's --bg-elevated
ACCENT_COLOR = (109, 123, 255)   # matches --accent
TEXT_COLOR = (238, 240, 247)     # matches --text
MUTED_COLOR = (136, 145, 168)    # matches --muted
BAR_BG_COLOR = (38, 44, 61)      # matches --border


def font(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_PATH), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass  # non-variable fallback font, or an unexpected weight name
    return f
