"""Info commands.

    !avatar [@user]
    !info                (owner only — bot-level stats)
    !serverinfo
    !userinfo [@user]

CAVEAT: `!serverinfo` and `!userinfo` display fields (member_count,
premium_tier, joined_at, flags/staff-rank) using the field names
Fluxer's guild/member/user objects are expected to carry given the
Discord-shaped conventions used elsewhere in its API. Exact field
names for boost tier and staff/flag bits aren't confirmed from public
docs — each lookup below falls back to "Unknown" rather than guessing
wrong, so nothing here will crash if a field is named differently on
your instance; you may just see "Unknown" until the field name is
corrected.
"""
from __future__ import annotations

import re

from bot.commands import Bot, Context
from bot.timeutil import format_date, format_duration, snowflake_to_datetime
from common.discovery import get_media_base, guild_icon_url, user_avatar_url

MENTION_RE = re.compile(r"^<@!?(\d+)>$")

# Best-effort: known Discord-style public flag bits that *might* map to
# Fluxer staff/verification badges. Unconfirmed — shown only if present.
STAFF_FLAGS = {
    1 << 0: "Staff",
    1 << 1: "Partner",
    1 << 2: "Verified",
    1 << 17: "Verified Bot Developer",
}


def _parse_id(token: str) -> str | None:
    m = MENTION_RE.match(token)
    if m:
        return m.group(1)
    if token.isdigit():
        return token
    return None


def _describe_flags(flags: int) -> str:
    names = [label for bit, label in STAFF_FLAGS.items() if flags & bit]
    return ", ".join(names) if names else "—"


def register(bot: Bot) -> None:

    @bot.command("avatar", category="Info", help_text="Show a member's avatar. Usage: !avatar [@user]")
    async def avatar(ctx: Context) -> None:
        target_user = ctx.author
        if ctx.args:
            user_id = _parse_id(ctx.args[0])
            if not user_id:
                await ctx.reply(f"Couldn't parse `{ctx.args[0]}` as a user.")
                return
            try:
                member = await ctx.bot.get_member(ctx.guild_id, user_id, fresh=True)
                target_user = member.get("user", member)
            except Exception:
                await ctx.reply("Couldn't find that member in this server.")
                return

        media_base = await get_media_base()
        url = user_avatar_url(media_base, str(target_user["id"]), target_user.get("avatar"))
        if not url:
            await ctx.reply(f"**{target_user.get('username', 'That user')}** has no custom avatar set.")
            return
        embed = {
            "title": f"{target_user.get('username', 'User')}'s avatar",
            "color": 0x5865F2,
            "image": {"url": url},
        }
        await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])

    @bot.command("info", category="Info", owner_only=True,
                 help_text="Bot stats and status (owner only). Usage: !info")
    async def info(ctx: Context) -> None:
        from common.config import config
        guild_count = await ctx.bot.guild_count()
        uptime = format_duration(ctx.bot.uptime_seconds)
        gw = ctx.bot.gateway
        latency = f"{gw.latency_ms:.0f}ms" if gw.latency_ms is not None else "n/a"
        bot_user = gw.user or {}

        embed = {
            "title": f"🤖 {config.bot_name} — bot info",
            "color": 0x5865F2,
            "fields": [
                {"name": "Bot user", "value": bot_user.get("username", "unknown"), "inline": True},
                {"name": "Servers", "value": str(guild_count), "inline": True},
                {"name": "Uptime", "value": uptime, "inline": True},
                {"name": "Gateway latency", "value": latency, "inline": True},
                {"name": "Commands loaded", "value": str(len(set(c.name for c in ctx.bot.commands.values()))),
                 "inline": True},
                {"name": "API base", "value": config.api_base, "inline": False},
            ],
        }
        await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])

    @bot.command("serverinfo", category="Info", aliases=["server"],
                 help_text="Server info: member count, owner, boost tier, and more. Usage: !serverinfo")
    async def serverinfo(ctx: Context) -> None:
        guild = ctx.guild or {}
        created = snowflake_to_datetime(str(guild.get("id", ctx.guild_id)))
        media_base = await get_media_base()
        icon_url = guild_icon_url(media_base, ctx.guild_id, guild.get("icon"))

        fields = [
            {"name": "Owner", "value": f"<@{guild.get('owner_id', 'Unknown')}>", "inline": True},
            {"name": "Members", "value": str(guild.get("member_count", "Unknown")), "inline": True},
            {"name": "Boost tier", "value": str(guild.get("premium_tier", guild.get("boost_tier", "Unknown"))),
             "inline": True},
            {"name": "Roles", "value": str(len(guild.get("roles", []))), "inline": True},
            {"name": "Channels", "value": str(len(guild.get("channels", []))), "inline": True},
            {"name": "Created", "value": format_date(created), "inline": True},
        ]
        embed = {
            "title": guild.get("name", "This server"),
            "description": f"ID: `{ctx.guild_id}`",
            "color": 0x5865F2,
            "fields": fields,
        }
        if icon_url:
            embed["thumbnail"] = {"url": icon_url}
        await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])

    @bot.command("userinfo", category="Info", aliases=["whois", "user"],
                 help_text="Profile info for a member: account age, join date, roles, staff rank. "
                            "Usage: !userinfo [@user]")
    async def userinfo(ctx: Context) -> None:
        member = ctx.member
        if ctx.args:
            user_id = _parse_id(ctx.args[0])
            if not user_id:
                await ctx.reply(f"Couldn't parse `{ctx.args[0]}` as a user.")
                return
            try:
                member = await ctx.bot.get_member(ctx.guild_id, user_id, fresh=True)
            except Exception:
                await ctx.reply("Couldn't find that member in this server.")
                return

        user = member.get("user", member)
        user_id = str(user.get("id"))
        created = snowflake_to_datetime(user_id)
        joined = member.get("joined_at")
        joined_str = joined[:10] if isinstance(joined, str) else "Unknown"

        role_ids = member.get("roles", [])
        roles_str = ", ".join(f"<@&{r}>" for r in role_ids[:15]) if role_ids else "None"

        flags = user.get("public_flags", user.get("flags", 0)) or 0
        staff_rank = _describe_flags(int(flags)) if isinstance(flags, int) else "—"

        media_base = await get_media_base()
        avatar_url = user_avatar_url(media_base, user_id, user.get("avatar"))

        embed = {
            "title": user.get("username", "User"),
            "description": f"ID: `{user_id}`",
            "color": 0x5865F2,
            "fields": [
                {"name": "Account created", "value": format_date(created), "inline": True},
                {"name": "Joined server", "value": joined_str, "inline": True},
                {"name": "Staff rank", "value": staff_rank, "inline": True},
                {"name": f"Roles ({len(role_ids)})", "value": roles_str, "inline": False},
            ],
        }
        if avatar_url:
            embed["thumbnail"] = {"url": avatar_url}
        await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])
