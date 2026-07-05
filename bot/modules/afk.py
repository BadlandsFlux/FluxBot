"""AFK status.

    !afk [reason]    mark yourself away; cleared automatically the next
                      time you send a message. Mentioning someone who's
                      AFK gets a note back with their reason and how
                      long they've been away.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bot.commands import Bot, Context
from bot.timeutil import format_duration
from common import db

MENTION_RE = re.compile(r"<@!?(\d+)>")


def _ago(since: datetime) -> str:
    seconds = (datetime.now(timezone.utc) - since).total_seconds()
    return format_duration(seconds)


def register(bot: Bot) -> None:

    @bot.command("afk", category="Utility", help_text="Mark yourself AFK. Usage: !afk [reason]")
    async def afk(ctx: Context) -> None:
        reason = " ".join(ctx.args) if ctx.args else "AFK"
        await db.set_afk(ctx.guild_id, str(ctx.author["id"]), reason)
        await ctx.reply(f"💤 You're now AFK: {reason}")

    @bot.on("MESSAGE_CREATE")
    async def on_message_afk(data: dict) -> None:
        guild_id = data.get("guild_id")
        author = data.get("author", {})
        if not guild_id or author.get("bot"):
            return
        user_id = str(author["id"])
        channel_id = data.get("channel_id")
        content = data.get("content", "") or ""

        cleared = await db.clear_afk(guild_id, user_id)
        if cleared:
            try:
                await bot.rest.send_message(
                    channel_id,
                    content=f"👋 Welcome back <@{user_id}>, I've cleared your AFK status.",
                    allowed_mentions=bot.rest.mention_only(user_id),
                )
            except Exception:
                pass

        mentioned_ids = list(dict.fromkeys(MENTION_RE.findall(content)))
        if not mentioned_ids:
            return
        afk_rows = await db.list_afk_for_users(guild_id, mentioned_ids)
        if not afk_rows:
            return

        lines = [f"💤 <@{row['user_id']}> is AFK: {row['reason']} ({_ago(row['since'])} ago)" for row in afk_rows]
        try:
            # No mentions honored here at all — the original message already
            # pinged them (that's Fluxer's normal behavior, out of our
            # hands), this follow-up is purely informational and shouldn't
            # ping anyone a second time.
            await bot.rest.send_message(channel_id, content="\n".join(lines),
                                         allowed_mentions=bot.rest.mention_only())
        except Exception:
            pass
