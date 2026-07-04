"""Leveling / XP.

Members earn XP for chatting (with a per-user cooldown to prevent
spam-leveling). Crossing a level threshold announces a level-up and
grants any role configured for that level (see the dashboard's Levels
tab, or !rank / !leaderboard to check progress).

    !rank [@user]
    !leaderboard

XP curve is the common "MEE6-style" formula: level N requires
5*N^2 + 50*N + 100 XP to clear, cumulative.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

from bot.commands import Bot, Context
from common import db

XP_MIN, XP_MAX = 15, 25
XP_COOLDOWN_SECONDS = 60


def xp_for_level(level: int) -> int:
    """XP required to advance from `level` to `level + 1`."""
    return 5 * level * level + 50 * level + 100


def level_for_xp(xp: int) -> int:
    level = 0
    remaining = xp
    while remaining >= xp_for_level(level):
        remaining -= xp_for_level(level)
        level += 1
    return level


def xp_progress(xp: int, level: int) -> tuple[int, int]:
    """Returns (xp_into_current_level, xp_needed_for_current_level)."""
    consumed = sum(xp_for_level(lv) for lv in range(level))
    return xp - consumed, xp_for_level(level)


def _bar(pct: float, width: int = 16) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


async def grant_xp(bot: Bot, guild_id: str, user_id: str, username: str, amount: int,
                    fallback_channel_id: str | None = None) -> None:
    """Add XP for a member and handle any resulting level-up (announcement +
    role rewards). Shared by both text-message XP (leveling.py) and voice-time
    XP (voice_tracker.py) so level-up behavior can't drift between the two
    sources — only the "how much XP, how often" logic differs upstream."""
    guild_cfg = await db.get_guild(guild_id)
    if not guild_cfg or not guild_cfg["leveling_enabled"]:
        return

    existing = await db.get_level(guild_id, user_id)
    old_level = existing["level"] if existing else 0
    row = await db.add_xp(guild_id, user_id, amount)
    new_level = level_for_xp(row["xp"])
    if new_level <= old_level:
        return

    await db.set_level(guild_id, user_id, new_level)
    channel_id = guild_cfg["level_up_channel_id"] or fallback_channel_id
    if channel_id:
        text = (
            guild_cfg["level_up_message"]
            .replace("{user}", f"<@{user_id}>")
            .replace("{username}", username)
            .replace("{level}", str(new_level))
        )
        try:
            await bot.rest.send_message(channel_id, content=text, allowed_mentions=bot.rest.mention_only(user_id))
        except Exception:
            pass

    for lvl in range(old_level + 1, new_level + 1):
        role_row = await db.get_level_role_for(guild_id, lvl)
        if role_row:
            try:
                await bot.rest.add_member_role(guild_id, user_id, role_row["role_id"])
            except Exception:
                pass


def register(bot: Bot) -> None:

    @bot.on("MESSAGE_CREATE")
    async def on_message_xp(data: dict) -> None:
        guild_id = data.get("guild_id")
        author = data.get("author", {})
        if not guild_id or author.get("bot"):
            return
        guild_cfg = await db.get_guild(guild_id)
        if not guild_cfg or not guild_cfg["leveling_enabled"]:
            return

        user_id = str(author["id"])
        existing = await db.get_level(guild_id, user_id)
        now = datetime.now(timezone.utc)
        if existing and existing["last_xp_at"] and (now - existing["last_xp_at"]).total_seconds() < XP_COOLDOWN_SECONDS:
            return

        await grant_xp(bot, guild_id, user_id, author.get("username", "someone"),
                        random.randint(XP_MIN, XP_MAX), fallback_channel_id=data.get("channel_id"))

    @bot.command("rank", category="Fun", aliases=["level"],
                 help_text="Show XP/level progress, messages sent, and voice time. Usage: !rank [@user]")
    async def rank(ctx: Context) -> None:
        target_id = str(ctx.author["id"])
        target_name = ctx.author.get("username", "You")
        if ctx.args:
            import re
            m = re.match(r"^<@!?(\d+)>$", ctx.args[0])
            target_id = m.group(1) if m else (ctx.args[0] if ctx.args[0].isdigit() else target_id)
            if target_id != str(ctx.author["id"]):
                try:
                    member = await ctx.bot.get_member(ctx.guild_id, target_id, fresh=True)
                    target_name = member.get("user", member).get("username", target_id)
                except Exception:
                    target_name = target_id

        row = await db.get_level(ctx.guild_id, target_id)
        if not row:
            await ctx.reply(f"**{target_name}** hasn't earned any XP yet.")
            return
        rank_pos = await db.get_rank(ctx.guild_id, target_id)
        into_level, needed = xp_progress(row["xp"], row["level"])
        pct = (into_level / needed) * 100 if needed else 0

        message_count = await db.get_member_message_count(ctx.guild_id, target_id)
        voice_minutes = await db.get_member_voice_minutes(ctx.guild_id, target_id)
        voice_hours = voice_minutes / 60

        embed = {
            "title": f"{target_name}'s rank",
            "color": 0x5865F2,
            "fields": [
                {"name": "Level", "value": str(row["level"]), "inline": True},
                {"name": "Rank", "value": f"#{rank_pos}", "inline": True},
                {"name": "Total XP", "value": str(row["xp"]), "inline": True},
                {"name": "Messages sent", "value": str(message_count), "inline": True},
                {"name": "Time in voice", "value": f"{voice_hours:.1f}h", "inline": True},
                {"name": "Progress", "value": f"{_bar(pct)} {into_level}/{needed} XP", "inline": False},
            ],
        }
        await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])

    @bot.command("leaderboard", category="Fun", aliases=["lb", "top"],
                 help_text="Show the server's XP leaderboard. Usage: !leaderboard")
    async def leaderboard(ctx: Context) -> None:
        rows = await db.get_leaderboard(ctx.guild_id, 10)
        if not rows:
            await ctx.reply("No one has earned XP yet.")
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, r in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`#{i + 1}`"
            lines.append(f"{prefix} <@{r['user_id']}> — level {r['level']} ({r['xp']} XP)")
        await ctx.embed("🏆 Leaderboard", "\n".join(lines))
