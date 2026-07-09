"""Visual rank card for !rank.

Generates a PNG (avatar, username, level/rank, XP progress bar, message
and voice stats) instead of a plain text embed. See bot/card_style.py
for the shared font/color setup used by this and other generated cards.

Anything that can go wrong here (missing avatar, a font/Pillow issue,
a network hiccup fetching the avatar) should fall back to the previous
plain-text embed rather than breaking the whole command over what's
fundamentally a cosmetic feature. See bot/modules/leveling.py's !rank
command for that fallback.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import aiohttp
from PIL import Image, ImageDraw

from bot.card_style import ACCENT_COLOR, BAR_BG_COLOR, CARD_COLOR, MUTED_COLOR, TEXT_COLOR, font

log = logging.getLogger("fluxbot.rank_card")

CARD_WIDTH, CARD_HEIGHT = 900, 260
AVATAR_SIZE = 160


def _circular(img: Image.Image, size: int) -> Image.Image:
    img = img.resize((size, size)).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    out = Image.new("RGBA", (size, size))
    out.paste(img, (0, 0), mask)
    return out


async def fetch_avatar(avatar_url: Optional[str]) -> Optional[Image.Image]:
    if not avatar_url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(avatar_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        return Image.open(io.BytesIO(data))
    except Exception:
        log.warning("Couldn't fetch avatar for rank card", exc_info=True)
        return None


def render(*, username: str, avatar_image: Optional[Image.Image], level: int, rank: int,
           xp_into_level: int, xp_needed: int, total_xp: int, messages: int, voice_hours: float) -> bytes:
    """Returns PNG bytes. Raises on any rendering failure, the caller is
    expected to catch that and fall back to the text embed."""
    card = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), CARD_COLOR)
    draw = ImageDraw.Draw(card)

    draw.rectangle([(0, 0), (8, CARD_HEIGHT)], fill=ACCENT_COLOR)

    pad = 36
    avatar_pos = (pad, (CARD_HEIGHT - AVATAR_SIZE) // 2)
    if avatar_image:
        circ = _circular(avatar_image, AVATAR_SIZE)
        card.paste(circ, avatar_pos, circ)
    else:
        draw.ellipse([avatar_pos, (avatar_pos[0] + AVATAR_SIZE, avatar_pos[1] + AVATAR_SIZE)], fill=ACCENT_COLOR)
        letter = (username[0] if username else "?").upper()
        f = font(64, "Bold")
        bbox = draw.textbbox((0, 0), letter, font=f)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            (avatar_pos[0] + AVATAR_SIZE / 2 - tw / 2, avatar_pos[1] + AVATAR_SIZE / 2 - th / 2 - bbox[1]),
            letter, font=f, fill=(255, 255, 255),
        )

    text_x = pad + AVATAR_SIZE + 36
    draw.text((text_x, 44), username, font=font(40, "Bold"), fill=TEXT_COLOR)
    draw.text((text_x, 96), f"Level {level}    Rank #{rank}", font=font(24, "Medium"), fill=MUTED_COLOR)

    bar_x, bar_y = text_x, 150
    bar_w, bar_h = CARD_WIDTH - text_x - pad, 28
    draw.rounded_rectangle([(bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h)], radius=bar_h // 2, fill=BAR_BG_COLOR)
    pct = min(1.0, xp_into_level / xp_needed) if xp_needed else 0
    if pct > 0:
        fill_w = max(bar_h, int(bar_w * pct))
        draw.rounded_rectangle([(bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h)], radius=bar_h // 2, fill=ACCENT_COLOR)
    draw.text(
        (bar_x, bar_y + bar_h + 10),
        f"{xp_into_level:,} / {xp_needed:,} XP ({total_xp:,} total)",
        font=font(18, "Regular"), fill=MUTED_COLOR,
    )

    stats_y = CARD_HEIGHT - 44
    draw.text(
        (text_x, stats_y),
        f"{messages:,} messages sent    {voice_hours:.1f}h in voice",
        font=font(18, "Regular"), fill=MUTED_COLOR,
    )

    buf = io.BytesIO()
    card.save(buf, format="PNG")
    return buf.getvalue()
