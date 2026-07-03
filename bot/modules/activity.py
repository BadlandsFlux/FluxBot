"""Activity tracking.

Increments a per-day guild message count and a per-user running total
on every human message. Deliberately decoupled from leveling (this
runs regardless of whether leveling is enabled) since server stats are
useful even for servers that don't want XP/levels turned on.
"""
from __future__ import annotations

from bot.commands import Bot
from common import db


def register(bot: Bot) -> None:

    @bot.on("MESSAGE_CREATE")
    async def on_message_activity(data: dict) -> None:
        guild_id = data.get("guild_id")
        author = data.get("author", {})
        if not guild_id or author.get("bot"):
            return
        try:
            await db.record_message(guild_id, str(author["id"]))
        except Exception:
            pass
