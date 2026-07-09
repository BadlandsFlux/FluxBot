"""Server Wrapped recap card for !wrapped.

All-time rather than period-specific ("this year", "this month"):
member-level message/voice counters are cumulative totals, not
date-bucketed per member (only the guild-wide daily totals are), so a
genuine "this year only" breakdown per member isn't available without
a whole new tracking system. All-time is the honest scope given what's
actually stored, this could grow into a real per-period feature later
if member-level history ever gets tracked.
"""
from __future__ import annotations

import io
from typing import Optional

from PIL import Image, ImageDraw

from bot.card_style import ACCENT_COLOR, BAR_BG_COLOR, CARD_COLOR, MUTED_COLOR, TEXT_COLOR, font

WIDTH, HEIGHT = 900, 620
PAD = 50


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def render(*, guild_name: str, total_messages: int, total_voice_hours: float,
           top_chatter: Optional[str], top_chatter_count: int,
           top_voice: Optional[str], top_voice_hours: float,
           members_with_xp: int, achievements_unlocked: int) -> bytes:
    """Returns PNG bytes. Raises on any rendering failure, the caller is
    expected to catch that and fall back to a plain-text version."""
    card = Image.new("RGB", (WIDTH, HEIGHT), CARD_COLOR)
    draw = ImageDraw.Draw(card)

    draw.rectangle([(0, 0), (WIDTH, 10)], fill=ACCENT_COLOR)

    draw.text((PAD, 46), _truncate(guild_name, 40), font=font(24, "Medium"), fill=MUTED_COLOR)
    draw.text((PAD, 76), "Wrapped", font=font(56, "Bold"), fill=TEXT_COLOR)
    draw.text((PAD, 148), "All-time, so far", font=font(16, "Regular"), fill=MUTED_COLOR)

    stats = [
        (f"{total_messages:,}", "messages sent"),
        (f"{total_voice_hours:,.0f}h", "spent in voice together"),
        (top_chatter and _truncate(top_chatter, 16) or "nobody yet",
         f"top chatter, {top_chatter_count:,} messages" if top_chatter else "top chatter"),
        (top_voice and _truncate(top_voice, 16) or "nobody yet",
         f"most time in voice, {top_voice_hours:,.0f}h" if top_voice else "most time in voice"),
        (f"{members_with_xp:,}", "members earning XP"),
        (f"{achievements_unlocked:,}", "achievements unlocked"),
    ]

    cols = 2
    gap = 20
    box_w = (WIDTH - PAD * 2 - gap) // cols
    box_h = 120
    start_y = 200

    for i, (value, label) in enumerate(stats):
        col, row = i % cols, i // cols
        x = PAD + col * (box_w + gap)
        y = start_y + row * (box_h + gap)
        draw.rounded_rectangle([(x, y), (x + box_w, y + box_h)], radius=14, fill=BAR_BG_COLOR)
        draw.text((x + 22, y + 20), value, font=font(30, "Bold"), fill=ACCENT_COLOR)
        draw.text((x + 22, y + 66), label, font=font(15, "Regular"), fill=MUTED_COLOR)

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    return buf.getvalue()
