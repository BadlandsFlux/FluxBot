"""Shared moderation actions.

Both chat commands (bot/modules/moderation.py) and dashboard-initiated
actions (dashboard/app.py's Members tab) call into these functions, so
logging and warn-escalation behavior can never drift between "someone
typed !warn" and "someone clicked Warn in the dashboard" — there's
exactly one implementation of each action.

`rest` is duck-typed: anything with the same async methods as
`bot.rest.FluxerREST` works, which in practice is either a running
bot's `Bot.rest` or the dashboard's standalone `bot_rest` client.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from bot.modules.logging_mod import log_and_notify
from bot.permissions import hierarchy_violation
from bot.rest import FluxerAPIError
from common import db

log = logging.getLogger("fluxbot.moderation_actions")

AUTOMOD = {"id": "0", "username": "AutoMod"}


class ModerationBlocked(Exception):
    """Raised when self/owner/role-hierarchy protection blocks an action,
    distinct from FluxerAPIError (the action was allowed but the REST call
    to Fluxer itself failed for some other reason). Both call sites (chat
    commands, dashboard) catch this and surface the message directly."""


def format_seconds(seconds: int) -> str:
    if seconds and seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds and seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds and seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


async def _check_can_moderate(rest, guild_id: str, moderator: dict, target_id: str) -> None:
    """Self/owner/role-hierarchy guard, shared by kick/ban/timeout/warn so
    it can't be bypassed by calling one entry point instead of another.
    Not applied to unban/untimeout: those lift a restriction rather than
    apply one, and unban's target isn't even a current guild member to
    check hierarchy against.

    Fails OPEN if we can't fetch the guild/member data needed to check
    (logged, not silently swallowed): this is defense-in-depth on top of
    the primary permission-bit gate in is_moderator(), not the only thing
    standing between an attacker and the action, so a transient API hiccup
    blocking all moderation outright would be a worse outcome than rarely
    missing this specific secondary check.
    """
    moderator_id = str(moderator.get("id"))
    target_id = str(target_id)
    if moderator_id == target_id:
        raise ModerationBlocked("You can't do that to yourself.")

    try:
        guild = await rest.get_guild(guild_id)
    except FluxerAPIError:
        log.warning("Couldn't fetch guild %s to check moderation hierarchy, allowing the action", guild_id)
        return

    if str(guild.get("owner_id")) == target_id:
        raise ModerationBlocked("You can't do that to the server owner.")
    if str(guild.get("owner_id")) == moderator_id:
        return

    try:
        moderator_member = await rest.get_guild_member(guild_id, moderator_id)
        target_member = await rest.get_guild_member(guild_id, target_id)
    except FluxerAPIError:
        log.warning("Couldn't fetch member roles in guild %s to check moderation hierarchy, allowing the action",
                    guild_id)
        return

    reason = hierarchy_violation(guild, moderator_id, moderator_member, target_id, target_member)
    if reason:
        raise ModerationBlocked(reason)


async def kick_member(rest, guild_id: str, user: dict, moderator: dict, reason: str = "") -> None:
    user_id = str(user["id"])
    await _check_can_moderate(rest, guild_id, moderator, user_id)
    await rest.kick_member(guild_id, user_id, reason)
    await log_and_notify(rest, guild_id, "kick", user=user, moderator=moderator, reason=reason)


async def ban_member(rest, guild_id: str, user: dict, moderator: dict, reason: str = "",
                      delete_message_seconds: int = 0) -> None:
    user_id = str(user["id"])
    await _check_can_moderate(rest, guild_id, moderator, user_id)
    await rest.ban_member(guild_id, user_id, reason, delete_message_seconds)
    await log_and_notify(rest, guild_id, "ban", user=user, moderator=moderator, reason=reason)


async def unban_member(rest, guild_id: str, user_id: str, moderator: dict, reason: str = "") -> None:
    await rest.unban_member(guild_id, user_id, reason)
    await log_and_notify(rest, guild_id, "unban", user={"id": user_id}, moderator=moderator, reason=reason)


async def timeout_member(rest, guild_id: str, user: dict, moderator: dict, seconds: int,
                          reason: str = "") -> None:
    user_id = str(user["id"])
    await _check_can_moderate(rest, guild_id, moderator, user_id)
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    await rest.timeout_member(guild_id, user_id, until.isoformat(), reason)
    await log_and_notify(rest, guild_id, "timeout", user=user, moderator=moderator, reason=reason,
                          extra_fields=[{"name": "Duration", "value": format_seconds(seconds), "inline": True}])


async def untimeout_member(rest, guild_id: str, user: dict, moderator: dict, reason: str = "") -> None:
    user_id = str(user["id"])
    await rest.remove_timeout(guild_id, user_id, reason)
    await log_and_notify(rest, guild_id, "untimeout", user=user, moderator=moderator, reason=reason)


async def warn_member(rest, guild_id: str, user: dict, moderator: dict, reason: str = "") -> dict:
    """Add a warning and apply auto-escalation per the guild's configured
    thresholds. Returns {active_count, escalated: None|"kick"|"timeout",
    timeout_minutes}."""
    user_id = str(user["id"])
    await _check_can_moderate(rest, guild_id, moderator, user_id)
    await db.add_warning(guild_id, user_id, str(moderator["id"]), reason)
    active_count = await db.count_active_warnings(guild_id, user_id)
    await log_and_notify(rest, guild_id, "warn", user=user, moderator=moderator, reason=reason,
                          extra_fields=[{"name": "Total active warnings", "value": str(active_count), "inline": True}])

    result = {"active_count": active_count, "escalated": None, "timeout_minutes": None}
    guild_cfg = await db.get_guild(guild_id)
    if not guild_cfg:
        return result

    if active_count >= guild_cfg["warn_kick_at"]:
        await rest.kick_member(guild_id, user_id, "Automatic: warning threshold reached")
        await log_and_notify(rest, guild_id, "kick", user=user, moderator=AUTOMOD,
                              reason=f"Reached {active_count} active warnings")
        result["escalated"] = "kick"
    elif active_count >= guild_cfg["warn_timeout_at"]:
        minutes = guild_cfg["warn_timeout_minutes"]
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await rest.timeout_member(guild_id, user_id, until.isoformat(), "Automatic: warning threshold reached")
        await log_and_notify(rest, guild_id, "timeout", user=user, moderator=AUTOMOD,
                              reason=f"Reached {active_count} active warnings",
                              extra_fields=[{"name": "Duration", "value": f"{minutes}m", "inline": True}])
        result["escalated"] = "timeout"
        result["timeout_minutes"] = minutes
    return result
