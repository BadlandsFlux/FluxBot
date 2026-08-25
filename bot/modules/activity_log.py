"""Configurable server activity logging.

Distinct from the existing mod_actions log (bot/modules/logging_mod.py),
which only covers moderation actions this bot itself took. This covers
broader server activity: message edits/deletes, member join/leave,
channel/role changes, and voice join/leave/switch, each independently
togglable, all posting to one configurable channel per guild.

Everything defaults OFF (see activity_log_settings in schema.sql): a
server that's never touched this feature shouldn't suddenly start
getting log messages the first time this code ships.

Message edit/delete logging depends on bot/message_cache.py, a runtime
cache of recent message content, since neither MESSAGE_UPDATE nor
MESSAGE_DELETE include the original text. See that module's docstring
for the tradeoffs.

Bot-authored messages are always excluded from edit/delete logging
(a bot editing its own embed, e.g. a live poll count, isn't useful
transparency information and would flood the log). There's no
separate toggle for this, it's just always off.
"""
from __future__ import annotations

from typing import Optional

from bot.commands import Bot
from bot import message_cache
from bot.timeutil import format_date, snowflake_to_datetime
from common import db

# Independent of voice_tracker.py's own per-member channel tracking
# (that one's about XP eligibility/accrual, this one's just "did they
# join/leave/switch"), decoupled on purpose so the two systems can't
# get tangled with each other. Same known limitation as voice_tracker's
# own tracking: a member already connected before this bot session
# started, who then only mutes/deafens without changing channel, could
# have their first real state-change event misread as a fresh "join"
# if GUILD_CREATE's voice_states seeding doesn't apply to them.
_last_channel: dict[tuple[str, str], Optional[str]] = {}


def _truncate(text: str, max_chars: int = 1000) -> str:
    text = text or ""
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


async def _send_log(bot: Bot, channel_id: str, embed: dict) -> None:
    try:
        await bot.rest.send_message(channel_id, embeds=[embed])
    except Exception:
        pass


def register(bot: Bot) -> None:

    @bot.on("GUILD_CREATE")
    async def on_guild_create_seed_voice(data: dict) -> None:
        guild_id = str(data.get("id"))
        for vs in data.get("voice_states", []) or []:
            user_id = vs.get("user_id")
            if user_id:
                _last_channel[(guild_id, str(user_id))] = str(vs["channel_id"]) if vs.get("channel_id") else None

    # ------------------------------------------------------------- messages --
    @bot.on("MESSAGE_CREATE")
    async def on_message_cache(data: dict) -> None:
        guild_id = data.get("guild_id")
        message_id = data.get("id")
        author = data.get("author", {})
        if not guild_id or not message_id or author.get("bot"):
            return
        message_cache.remember(
            str(message_id), guild_id=str(guild_id), channel_id=str(data.get("channel_id")),
            author_id=str(author.get("id")), author_username=author.get("username", "unknown"),
            content=data.get("content", "") or "",
        )

    @bot.on("MESSAGE_UPDATE")
    async def on_message_update(data: dict) -> None:
        guild_id = data.get("guild_id")
        message_id = data.get("id")
        new_content = data.get("content")
        if not guild_id or not message_id or new_content is None:
            return  # some updates carry no content change (e.g. an embed-only link unfurl)
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_message_edits"]:
            return
        cached = message_cache.get(str(message_id))
        if not cached:
            return  # nothing to diff against, wasn't cached (bot restarted, or aged out)
        if cached["content"] == new_content:
            message_cache.update_content(str(message_id), new_content)
            return
        if await db.is_ignored_log_user(guild_id, cached["author_id"]):
            return

        embed = {
            "title": "Message edited",
            "color": 0xF5A623,
            "description": f"<@{cached['author_id']}> in <#{cached['channel_id']}>",
            "fields": [
                {"name": "Before", "value": _truncate(cached["content"]) or "*(empty)*", "inline": False},
                {"name": "After", "value": _truncate(new_content) or "*(empty)*", "inline": False},
            ],
        }
        await _send_log(bot, settings["log_channel_id"], embed)
        message_cache.update_content(str(message_id), new_content)

    @bot.on("MESSAGE_DELETE")
    async def on_message_delete(data: dict) -> None:
        guild_id = data.get("guild_id")
        message_id = data.get("id")
        if not guild_id or not message_id:
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_message_deletes"]:
            message_cache.forget(str(message_id))
            return

        cached = message_cache.get(str(message_id))
        if cached:
            if cached["author_id"] and await db.is_ignored_log_user(guild_id, cached["author_id"]):
                message_cache.forget(str(message_id))
                return
            embed = {
                "title": "Message deleted",
                "color": 0xE0245E,
                "description": f"<@{cached['author_id']}> in <#{cached['channel_id']}>",
                "fields": [{"name": "Content", "value": _truncate(cached["content"]) or "*(empty)*", "inline": False}],
            }
        else:
            channel_id = data.get("channel_id")
            embed = {
                "title": "Message deleted",
                "color": 0xE0245E,
                "description": (f"In <#{channel_id}>. " if channel_id else "")
                + "Content not available (not cached during this bot session).",
            }
        await _send_log(bot, settings["log_channel_id"], embed)
        message_cache.forget(str(message_id))

    # ---------------------------------------------------------------- members --
    @bot.on("GUILD_MEMBER_ADD")
    async def on_member_add(data: dict) -> None:
        guild_id = data.get("guild_id")
        user = data.get("user", {})
        if not guild_id or not user.get("id"):
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_member_joins"]:
            return
        if await db.is_ignored_log_user(guild_id, str(user["id"])):
            return
        created_at = snowflake_to_datetime(str(user["id"]))
        age_note = f"\nAccount created {format_date(created_at)}" if created_at else ""
        embed = {
            "title": "Member joined",
            "color": 0x4ADE80,
            "description": f"<@{user['id']}> ({user.get('username', 'unknown')}){age_note}",
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    @bot.on("GUILD_MEMBER_REMOVE")
    async def on_member_remove(data: dict) -> None:
        guild_id = data.get("guild_id")
        user = data.get("user", {})
        if not guild_id or not user.get("id"):
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_member_leaves"]:
            return
        if await db.is_ignored_log_user(guild_id, str(user["id"])):
            return
        embed = {
            "title": "Member left",
            "color": 0xF16565,
            "description": f"<@{user['id']}> ({user.get('username', 'unknown')})",
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    # --------------------------------------------------------------- channels --
    @bot.on("CHANNEL_CREATE")
    async def on_channel_create(data: dict) -> None:
        guild_id = data.get("guild_id")
        if not guild_id:
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_channel_changes"]:
            return
        embed = {
            "title": "Channel created",
            "color": 0x4ADE80,
            "description": f"#{data.get('name', 'unknown')} (`{data.get('id')}`)",
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    @bot.on("CHANNEL_DELETE")
    async def on_channel_delete(data: dict) -> None:
        guild_id = data.get("guild_id")
        if not guild_id:
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_channel_changes"]:
            return
        embed = {
            "title": "Channel deleted",
            "color": 0xE0245E,
            "description": f"#{data.get('name', 'unknown')} (`{data.get('id')}`)",
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    @bot.on("CHANNEL_UPDATE")
    async def on_channel_update(data: dict) -> None:
        guild_id = data.get("guild_id")
        if not guild_id:
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_channel_changes"]:
            return
        # Doesn't show a before/after diff of what specifically changed
        # (name, permissions, topic, etc.), that would need caching full
        # channel objects the same way messages are cached, a bigger
        # undertaking than this feature's current scope. Just notes that
        # something about the channel changed.
        embed = {
            "title": "Channel updated",
            "color": 0xF5A623,
            "description": f"#{data.get('name', 'unknown')} (`{data.get('id')}`)",
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    # ------------------------------------------------------------------ roles --
    @bot.on("GUILD_ROLE_CREATE")
    async def on_role_create(data: dict) -> None:
        guild_id = data.get("guild_id")
        role = data.get("role", {})
        if not guild_id:
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_role_changes"]:
            return
        embed = {
            "title": "Role created",
            "color": 0x4ADE80,
            "description": f"@{role.get('name', 'unknown')} (`{role.get('id')}`)",
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    @bot.on("GUILD_ROLE_DELETE")
    async def on_role_delete(data: dict) -> None:
        guild_id = data.get("guild_id")
        role_id = data.get("role_id")
        if not guild_id:
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_role_changes"]:
            return
        embed = {"title": "Role deleted", "color": 0xE0245E, "description": f"Role ID `{role_id}`"}
        await _send_log(bot, settings["log_channel_id"], embed)

    @bot.on("GUILD_ROLE_UPDATE")
    async def on_role_update(data: dict) -> None:
        guild_id = data.get("guild_id")
        role = data.get("role", {})
        if not guild_id:
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_role_changes"]:
            return
        embed = {
            "title": "Role updated",
            "color": 0xF5A623,
            "description": f"@{role.get('name', 'unknown')} (`{role.get('id')}`)",
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    # ------------------------------------------------------------------ voice --
    @bot.on("VOICE_STATE_UPDATE")
    async def on_voice_state_update(data: dict) -> None:
        guild_id = data.get("guild_id")
        user_id = data.get("user_id")
        if not guild_id or not user_id:
            return
        guild_id, user_id = str(guild_id), str(user_id)
        raw_channel = data.get("channel_id")
        new_channel = str(raw_channel) if raw_channel else None

        key = (guild_id, user_id)
        old_channel = _last_channel.get(key)
        _last_channel[key] = new_channel

        if old_channel == new_channel:
            return  # a mute/deafen toggle, not a channel change

        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_voice_activity"]:
            return
        if await db.is_ignored_log_user(guild_id, user_id):
            return

        if old_channel is None:
            title, color = "Joined voice", 0x4ADE80
            desc = f"<@{user_id}> joined <#{new_channel}>"
        elif new_channel is None:
            title, color = "Left voice", 0xF16565
            desc = f"<@{user_id}> left <#{old_channel}>"
        else:
            title, color = "Switched voice channel", 0xF5A623
            desc = f"<@{user_id}> moved from <#{old_channel}> to <#{new_channel}>"

        await _send_log(bot, settings["log_channel_id"], {"title": title, "color": color, "description": desc})
