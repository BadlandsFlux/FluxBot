"""Moderation commands.

    !kick @user [reason]
    !ban @user [reason]              (optionally: --delete 1d to purge recent msgs)
    !unban <user_id> [reason]
    !timeout @user <duration> [reason]   e.g. 10m, 2h, 1d
    !untimeout @user [reason]
    !purge <count>
    !warn @user [reason]
    !warnings @user
    !clearwarnings @user
    !modlog #channel                 (sets the mod-log channel)
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone

from bot.commands import Bot, Context
from bot.modules.logging_mod import log_and_notify
from bot.permissions import PERM_BAN_MEMBERS, PERM_KICK_MEMBERS, PERM_MANAGE_GUILD, PERM_MANAGE_MESSAGES, PERM_MODERATE_MEMBERS
from common import db

MENTION_RE = re.compile(r"^<@!?(\d+)>$")
CHANNEL_MENTION_RE = re.compile(r"^<#(\d+)>$")
DURATION_RE = re.compile(r"^(\d+)([smhdw])$")
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_id(token: str) -> str | None:
    m = MENTION_RE.match(token)
    if m:
        return m.group(1)
    if token.isdigit():
        return token
    return None


def parse_channel_id(token: str) -> str | None:
    m = CHANNEL_MENTION_RE.match(token)
    if m:
        return m.group(1)
    if token.isdigit():
        return token
    return None


def parse_duration_seconds(token: str) -> int | None:
    m = DURATION_RE.match(token.lower())
    if not m:
        return None
    value, unit = m.groups()
    return int(value) * DURATION_UNITS[unit]


async def _resolve_target(ctx: Context) -> tuple[dict | None, list[str]]:
    """Pull the first arg as a user id, fetch their member object. Returns (member, remaining_args)."""
    if not ctx.args:
        await ctx.reply("Mention a user or give their ID.")
        return None, []
    user_id = parse_id(ctx.args[0])
    if not user_id:
        await ctx.reply(f"Couldn't parse `{ctx.args[0]}` as a user.")
        return None, []
    try:
        member = await ctx.bot.get_member(ctx.guild_id, user_id, fresh=True)
    except Exception:
        await ctx.reply("Couldn't find that member in this server.")
        return None, []
    return member, ctx.args[1:]


def register(bot: Bot) -> None:

    @bot.command("kick", required_permission=PERM_KICK_MEMBERS,
                 help_text="Kick a member. Usage: !kick @user [reason]")
    async def kick(ctx: Context) -> None:
        member, rest = await _resolve_target(ctx)
        if member is None:
            return
        reason = " ".join(rest) or "No reason provided"
        user = member.get("user", member)
        await ctx.bot.rest.kick_member(ctx.guild_id, str(user["id"]), reason)
        await log_and_notify(ctx.bot, ctx.guild_id, "kick", user=user, moderator=ctx.author, reason=reason)
        await ctx.reply(f"👢 Kicked **{user.get('username', user['id'])}**. Reason: {reason}")

    @bot.command("ban", required_permission=PERM_BAN_MEMBERS,
                 help_text="Ban a member. Usage: !ban @user [reason]")
    async def ban(ctx: Context) -> None:
        member, rest = await _resolve_target(ctx)
        if member is None:
            return
        reason = " ".join(rest) or "No reason provided"
        user = member.get("user", member)
        await ctx.bot.rest.ban_member(ctx.guild_id, str(user["id"]), reason)
        await log_and_notify(ctx.bot, ctx.guild_id, "ban", user=user, moderator=ctx.author, reason=reason)
        await ctx.reply(f"🔨 Banned **{user.get('username', user['id'])}**. Reason: {reason}")

    @bot.command("unban", required_permission=PERM_BAN_MEMBERS,
                 help_text="Unban by user ID. Usage: !unban <user_id> [reason]")
    async def unban(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Give the user ID to unban.")
            return
        user_id = parse_id(ctx.args[0])
        if not user_id:
            await ctx.reply(f"Couldn't parse `{ctx.args[0]}` as a user ID.")
            return
        reason = " ".join(ctx.args[1:]) or "No reason provided"
        await ctx.bot.rest.unban_member(ctx.guild_id, user_id, reason)
        await log_and_notify(ctx.bot, ctx.guild_id, "unban", user={"id": user_id},
                              moderator=ctx.author, reason=reason)
        await ctx.reply(f"✅ Unbanned `{user_id}`. Reason: {reason}")

    @bot.command("timeout", aliases=["mute"], required_permission=PERM_MODERATE_MEMBERS,
                 help_text="Timeout a member. Usage: !timeout @user <duration> [reason], e.g. !timeout @user 1h spamming")
    async def timeout(ctx: Context) -> None:
        member, rest = await _resolve_target(ctx)
        if member is None:
            return
        if not rest:
            await ctx.reply("Give a duration, e.g. `10m`, `2h`, `1d`.")
            return
        seconds = parse_duration_seconds(rest[0])
        if seconds is None:
            await ctx.reply(f"Couldn't parse duration `{rest[0]}`. Use e.g. `10m`, `2h`, `1d`.")
            return
        reason = " ".join(rest[1:]) or "No reason provided"
        until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        user = member.get("user", member)
        await ctx.bot.rest.timeout_member(ctx.guild_id, str(user["id"]), until.isoformat(), reason)
        await log_and_notify(ctx.bot, ctx.guild_id, "timeout", user=user, moderator=ctx.author, reason=reason,
                              extra_fields=[{"name": "Duration", "value": rest[0], "inline": True}])
        await ctx.reply(f"🔇 Timed out **{user.get('username', user['id'])}** for {rest[0]}. Reason: {reason}")

    @bot.command("untimeout", aliases=["unmute"], required_permission=PERM_MODERATE_MEMBERS,
                 help_text="Remove a timeout. Usage: !untimeout @user [reason]")
    async def untimeout(ctx: Context) -> None:
        member, rest = await _resolve_target(ctx)
        if member is None:
            return
        reason = " ".join(rest) or "No reason provided"
        user = member.get("user", member)
        await ctx.bot.rest.remove_timeout(ctx.guild_id, str(user["id"]), reason)
        await log_and_notify(ctx.bot, ctx.guild_id, "untimeout", user=user, moderator=ctx.author, reason=reason)
        await ctx.reply(f"🔊 Removed timeout for **{user.get('username', user['id'])}**.")

    @bot.command("purge", aliases=["clear"], required_permission=PERM_MANAGE_MESSAGES,
                 help_text="Bulk delete recent messages. Usage: !purge <count 1-100>")
    async def purge(ctx: Context) -> None:
        if not ctx.args or not ctx.args[0].isdigit():
            await ctx.reply("Give a number of messages to delete (1-100).")
            return
        count = max(1, min(100, int(ctx.args[0])))
        messages = await ctx.bot.rest.get_channel_messages(ctx.channel_id, limit=count)
        message_ids = [str(m["id"]) for m in messages]
        if not message_ids:
            await ctx.reply("Nothing to delete.")
            return
        if len(message_ids) == 1:
            await ctx.bot.rest.delete_message(ctx.channel_id, message_ids[0])
        else:
            await ctx.bot.rest.bulk_delete_messages(ctx.channel_id, message_ids)
        await log_and_notify(ctx.bot, ctx.guild_id, "purge", moderator=ctx.author,
                              reason=f"{len(message_ids)} messages in <#{ctx.channel_id}>")
        await ctx.reply(f"🧹 Deleted {len(message_ids)} messages.")

    @bot.command("warn", required_permission=PERM_KICK_MEMBERS,
                 help_text="Warn a member. Usage: !warn @user [reason]")
    async def warn(ctx: Context) -> None:
        member, rest = await _resolve_target(ctx)
        if member is None:
            return
        reason = " ".join(rest) or "No reason provided"
        user = member.get("user", member)
        user_id = str(user["id"])
        await db.add_warning(ctx.guild_id, user_id, str(ctx.author["id"]), reason)
        active_count = await db.count_active_warnings(ctx.guild_id, user_id)
        await log_and_notify(ctx.bot, ctx.guild_id, "warn", user=user, moderator=ctx.author, reason=reason,
                              extra_fields=[{"name": "Total active warnings", "value": str(active_count), "inline": True}])
        await ctx.reply(f"⚠️ Warned **{user.get('username', user_id)}** ({active_count} active warning"
                         f"{'s' if active_count != 1 else ''}). Reason: {reason}")

        guild_cfg = await db.get_guild(ctx.guild_id)
        if not guild_cfg:
            return
        if active_count >= guild_cfg["warn_kick_at"]:
            await ctx.bot.rest.kick_member(ctx.guild_id, user_id, "Automatic: warning threshold reached")
            await log_and_notify(ctx.bot, ctx.guild_id, "kick", user=user,
                                  moderator={"id": "0", "username": "AutoMod"},
                                  reason=f"Reached {active_count} active warnings")
            await ctx.reply(f"🚨 **{user.get('username', user_id)}** hit the warning limit and was auto-kicked.")
        elif active_count >= guild_cfg["warn_timeout_at"]:
            minutes = guild_cfg["warn_timeout_minutes"]
            until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            await ctx.bot.rest.timeout_member(ctx.guild_id, user_id, until.isoformat(),
                                               "Automatic: warning threshold reached")
            await log_and_notify(ctx.bot, ctx.guild_id, "timeout", user=user,
                                  moderator={"id": "0", "username": "AutoMod"},
                                  reason=f"Reached {active_count} active warnings",
                                  extra_fields=[{"name": "Duration", "value": f"{minutes}m", "inline": True}])
            await ctx.reply(f"🚨 **{user.get('username', user_id)}** hit the warning threshold and was "
                             f"auto-timed-out for {minutes}m.")

    @bot.command("warnings", aliases=["infractions"],
                 help_text="List a member's warnings. Usage: !warnings @user")
    async def warnings_cmd(ctx: Context) -> None:
        member, _ = await _resolve_target(ctx)
        if member is None:
            return
        user = member.get("user", member)
        rows = await db.list_warnings(ctx.guild_id, str(user["id"]))
        if not rows:
            await ctx.reply(f"**{user.get('username', user['id'])}** has no warnings.")
            return
        lines = []
        for r in rows[:10]:
            status = "active" if r["active"] else "cleared"
            when = r["created_at"].strftime("%Y-%m-%d") if hasattr(r["created_at"], "strftime") else r["created_at"]
            lines.append(f"`#{r['id']}` [{status}] {when} — {r['reason']}")
        await ctx.embed(f"Warnings for {user.get('username', user['id'])}", "\n".join(lines))

    @bot.command("clearwarnings", aliases=["unwarn"], required_permission=PERM_KICK_MEMBERS,
                 help_text="Clear a member's active warnings. Usage: !clearwarnings @user")
    async def clear_warnings_cmd(ctx: Context) -> None:
        member, _ = await _resolve_target(ctx)
        if member is None:
            return
        user = member.get("user", member)
        cleared = await db.clear_warnings(ctx.guild_id, str(user["id"]))
        await log_and_notify(ctx.bot, ctx.guild_id, "clearwarnings", user=user, moderator=ctx.author,
                              reason=f"Cleared {cleared} warning(s)")
        await ctx.reply(f"🧾 Cleared {cleared} warning(s) for **{user.get('username', user['id'])}**.")

    @bot.command("modlog", required_permission=PERM_MANAGE_GUILD,
                 help_text="Set the mod-log channel. Usage: !modlog #channel")
    async def modlog(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Mention the channel to use for mod logs, e.g. `!modlog #mod-log`.")
            return
        channel_id = parse_channel_id(ctx.args[0])
        if not channel_id:
            await ctx.reply(f"Couldn't parse `{ctx.args[0]}` as a channel.")
            return
        await db.update_guild_settings(ctx.guild_id, log_channel_id=channel_id)
        await ctx.reply(f"📋 Mod-log channel set to <#{channel_id}>.")
