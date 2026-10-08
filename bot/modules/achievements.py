"""Achievements.

A small set of milestone badges, checked opportunistically whenever
the relevant counter changes (message count, level, voice minutes)
rather than on a schedule. Silent grants, no channel announcement,
since voice-time milestones in particular aren't tied to any specific
channel to post in. View them with !achievements.
"""
from __future__ import annotations

import re

from bot.commands import Bot, Context
from common import db

ACHIEVEMENTS = {
    "first_message": {"name": "First Words", "emoji": "💬", "description": "Sent your first message"},
    "chatterbox_100": {"name": "Chatterbox", "emoji": "🗣️", "description": "Sent 100 messages"},
    "chatterbox_1000": {"name": "Motormouth", "emoji": "📢", "description": "Sent 1,000 messages"},
    "chatterbox_5000": {"name": "Keyboard Warrior", "emoji": "⌨️", "description": "Sent 5,000 messages"},
    "chatterbox_10000": {"name": "Unhinged", "emoji": "🔥", "description": "Sent 10,000 messages"},
    "level_5": {"name": "Getting Started", "emoji": "⭐", "description": "Reached level 5"},
    "level_10": {"name": "Regular", "emoji": "🌟", "description": "Reached level 10"},
    "level_25": {"name": "Veteran", "emoji": "🏆", "description": "Reached level 25"},
    "level_50": {"name": "Certified No-Lifer", "emoji": "🩸", "description": "Reached level 50"},
    "level_100": {"name": "Triple-Digit Legend", "emoji": "💀", "description": "Reached level 100"},
    "level_150": {"name": "Unemployable (Confirmed)", "emoji": "🚬", "description": "Reached level 150"},
    "level_200": {"name": "The Server's Final Boss", "emoji": "👹", "description": "Reached level 200"},
    "level_250": {"name": "Touched Grass Once, Filed A Complaint", "emoji": "☠️",
                  "description": "Reached level 250, the top of the curve"},
    "voice_10h": {"name": "Talkative", "emoji": "🎙️", "description": "10 hours in voice chat"},
    "voice_50h": {"name": "Voice Regular", "emoji": "📻", "description": "50 hours in voice chat"},
    "voice_100h": {"name": "Living In Voice", "emoji": "🎧", "description": "100 hours in voice chat"},
    "voice_250h": {"name": "Permanent Dent In The Couch", "emoji": "🛋️", "description": "250 hours in voice chat"},
    "repeat_offender": {"name": "Repeat Offender", "emoji": "🚨", "description": "Racked up 3 or more warnings"},
    "menace": {"name": "Menace To Society", "emoji": "☣️", "description": "Racked up 10 or more warnings"},
    "whistleblower": {"name": "Whistleblower", "emoji": "🕵️", "description": "Filed 5 or more bug/issue reports"},
    "wordsmith": {"name": "Wordsmith", "emoji": "📝", "description": "Created 5 or more tags"},
}

MESSAGE_THRESHOLDS = [
    (1, "first_message"), (100, "chatterbox_100"), (1000, "chatterbox_1000"),
    (5000, "chatterbox_5000"), (10000, "chatterbox_10000"),
]
LEVEL_THRESHOLDS = [
    (5, "level_5"), (10, "level_10"), (25, "level_25"), (50, "level_50"),
    (100, "level_100"), (150, "level_150"), (200, "level_200"), (250, "level_250"),
]
VOICE_HOUR_THRESHOLDS = [(10, "voice_10h"), (50, "voice_50h"), (100, "voice_100h"), (250, "voice_250h")]
WARNING_THRESHOLDS = [(3, "repeat_offender"), (10, "menace")]
REPORT_THRESHOLDS = [(5, "whistleblower")]
TAG_THRESHOLDS = [(5, "wordsmith")]


async def check_message_achievements(guild_id: str, user_id: str) -> None:
    count = await db.get_member_message_count(guild_id, user_id)
    for threshold, key in MESSAGE_THRESHOLDS:
        if count >= threshold:
            await db.grant_achievement(guild_id, user_id, key)


async def check_level_achievements(guild_id: str, user_id: str) -> None:
    row = await db.get_level(guild_id, user_id)
    if not row:
        return
    for threshold, key in LEVEL_THRESHOLDS:
        if row["level"] >= threshold:
            await db.grant_achievement(guild_id, user_id, key)


async def check_voice_achievements(guild_id: str, user_id: str) -> None:
    minutes = await db.get_member_voice_minutes(guild_id, user_id)
    hours = minutes / 60
    for threshold, key in VOICE_HOUR_THRESHOLDS:
        if hours >= threshold:
            await db.grant_achievement(guild_id, user_id, key)


async def check_warning_achievements(guild_id: str, user_id: str) -> None:
    # Total ever received, not just currently-active ones: clearing a
    # member's warnings later shouldn't un-earn a badge for having
    # racked them up in the first place.
    count = len(await db.list_warnings(guild_id, user_id))
    for threshold, key in WARNING_THRESHOLDS:
        if count >= threshold:
            await db.grant_achievement(guild_id, user_id, key)


async def check_report_achievements(guild_id: str, user_id: str) -> None:
    count = await db.get_report_count_by_reporter(guild_id, user_id)
    for threshold, key in REPORT_THRESHOLDS:
        if count >= threshold:
            await db.grant_achievement(guild_id, user_id, key)


async def check_tag_achievements(guild_id: str, user_id: str) -> None:
    rows = await db.list_tags(guild_id)
    count = sum(1 for r in rows if r["created_by"] == user_id)
    for threshold, key in TAG_THRESHOLDS:
        if count >= threshold:
            await db.grant_achievement(guild_id, user_id, key)


def register(bot: Bot) -> None:

    @bot.on("MESSAGE_CREATE")
    async def on_message_achievements(data: dict) -> None:
        guild_id = data.get("guild_id")
        author = data.get("author", {})
        if not guild_id or author.get("bot"):
            return
        user_id = str(author["id"])
        await check_message_achievements(guild_id, user_id)
        await check_level_achievements(guild_id, user_id)

    @bot.command("achievements", category="Fun", aliases=["badges"],
                 help_text="Show earned achievements. Usage: !achievements [@user]")
    async def achievements_cmd(ctx: Context) -> None:
        target_id = str(ctx.author["id"])
        target_name = ctx.author.get("username", "You")
        if ctx.args:
            m = re.match(r"^<@!?(\d+)>$", ctx.args[0])
            target_id = m.group(1) if m else (ctx.args[0] if ctx.args[0].isdigit() else target_id)
            if target_id != str(ctx.author["id"]):
                try:
                    member = await ctx.bot.get_member(ctx.guild_id, target_id, fresh=True)
                    target_name = member.get("user", member).get("username", target_id)
                except Exception:
                    target_name = target_id

        rows = await db.list_achievements(ctx.guild_id, target_id)
        earned_keys = {r["key"] for r in rows}
        lines = []
        for key, meta in ACHIEVEMENTS.items():
            marker = "✅" if key in earned_keys else "▫️"
            lines.append(f"{marker} {meta['emoji']} **{meta['name']}**, {meta['description']}")
        await ctx.embed(f"{target_name}'s achievements ({len(earned_keys)}/{len(ACHIEVEMENTS)})", "\n".join(lines))
