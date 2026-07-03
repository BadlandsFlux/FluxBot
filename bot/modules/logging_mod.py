"""Mod-action logging.

Every moderation action (kick/ban/timeout/warn/purge/etc) gets:
  1. persisted to the `mod_actions` table (so the dashboard can show
     history even if the log channel is deleted or missing), and
  2. posted as an embed into the guild's configured log channel, if
     one has been set via the dashboard or `!modlog #channel`.
"""
from __future__ import annotations

import time
from typing import Optional

from common import db

ACTION_COLORS = {
    "kick": 0xE67E22,
    "ban": 0xE74C3C,
    "unban": 0x2ECC71,
    "timeout": 0xF1C40F,
    "untimeout": 0x2ECC71,
    "warn": 0xF39C12,
    "clearwarnings": 0x3498DB,
    "purge": 0x95A5A6,
}


def _user_tag(user: dict) -> str:
    username = user.get("username", "unknown")
    disc = user.get("discriminator")
    if disc and disc != "0":
        return f"{username}#{disc}"
    return f"@{username}"


async def log_and_notify(rest, guild_id: str, action: str, *, user: Optional[dict] = None,
                          moderator: Optional[dict] = None, reason: str = "",
                          extra_fields: Optional[list[dict]] = None) -> None:
    """`rest` is anything with an async `.send_message(channel_id, embeds=...)` —
    either a bot's `Bot.rest` (chat commands) or the dashboard's standalone
    `FluxerREST` instance (dashboard-initiated actions). This lets both paths
    log identically instead of the dashboard needing its own copy."""
    user_id = str(user.get("id")) if user else ""
    mod_id = str(moderator.get("id")) if moderator else ""

    await db.log_action(guild_id, action, user_id=user_id, moderator_id=mod_id, reason=reason)

    guild = await db.get_guild(guild_id)
    log_channel_id = guild["log_channel_id"] if guild else None
    if not log_channel_id:
        return

    fields = [
        {"name": "User", "value": _user_tag(user) + f" (`{user_id}`)" if user else "—", "inline": True},
        {"name": "Moderator", "value": _user_tag(moderator) + f" (`{mod_id}`)" if moderator else "System", "inline": True},
    ]
    if reason:
        fields.append({"name": "Reason", "value": reason, "inline": False})
    if extra_fields:
        fields.extend(extra_fields)

    embed = {
        "title": action.replace("_", " ").title(),
        "color": ACTION_COLORS.get(action, 0x5865F2),
        "fields": fields,
        "timestamp": None,
    }
    try:
        await rest.send_message(log_channel_id, embeds=[embed])
    except Exception:
        # Log channel might have been deleted / bot kicked from it —
        # don't let logging failures break the underlying mod action.
        pass
