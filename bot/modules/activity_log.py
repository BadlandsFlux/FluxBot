"""Configurable server activity logging.

Distinct from the existing mod_actions log (bot/modules/logging_mod.py),
which only covers moderation actions this bot itself took. This covers
broader server activity: message edits/deletes, member join/leave,
channel/role changes, voice join/leave/switch, and privileged role
grants/revokes on members, each independently togglable, all posting to
one configurable channel per guild.

Everything defaults OFF (see activity_log_settings in schema.sql): a
server that's never touched this feature shouldn't suddenly start
getting log messages the first time this code ships.

Message edit/delete logging depends on bot/message_cache.py, a runtime
cache of recent message content, since neither MESSAGE_UPDATE nor
MESSAGE_DELETE include the original text. See that module's docstring
for the tradeoffs.

WHO did a channel/role create/delete, or a role permission change, isn't
in the gateway event itself, Discord's (and presumably Fluxer's) audit
log is a genuinely separate thing from the object-change events. Rather
than block the whole gateway's event loop waiting on that lookup (every
event is awaited sequentially by bot/client.py's _dispatch, see the
comment on _spawn_actor_lookup below for why that matters), the base
log entry goes out immediately and a background task edits in a
"Performed By" field a moment later if the audit log resolves an actor.

Bot-authored messages are always excluded from edit/delete logging
(a bot editing its own embed, e.g. a live poll count, isn't useful
transparency information and would flood the log). There's no
separate toggle for this, it's just always off.

Every embed carries a native Discord/Fluxer embed timestamp (renders
in the viewer's own locale/format, with a hover for the exact time),
an author block with avatar where a specific user is involved, and a
footer with the relevant raw ID(s) for anyone who needs to reference
the exact user/message/channel/role. Message edits/deletes also get a
jump link straight to the message, built from FLUXER_WEB_BASE, so this
still points at the right place on a self-hosted instance.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from bot.bounded_cache import BoundedDict
from bot.commands import Bot
from bot import message_cache
from bot.permissions import decode_permissions, role_is_privileged
from bot.timeutil import format_date, snowflake_to_datetime
from common import db
from common.config import config
from common.discovery import get_media_base, user_avatar_url

log = logging.getLogger("fluxbot.activity_log")

# Discord's audit-log action_type enum (best-effort assumption,
# unconfirmed for Fluxer specifically, same caveat as everywhere else
# this project relies on Discord-convention numeric constants).
AUDIT_LOG_CHANNEL_CREATE = 10
AUDIT_LOG_CHANNEL_DELETE = 12
AUDIT_LOG_ROLE_CREATE = 30
AUDIT_LOG_ROLE_UPDATE = 31
AUDIT_LOG_ROLE_DELETE = 32

# Independent of voice_tracker.py's own per-member channel tracking
# (that one's about XP eligibility/accrual, this one's just "did they
# join/leave/switch"), decoupled on purpose so the two systems can't
# get tangled with each other. Same known limitation as voice_tracker's
# own tracking: a member already connected before this bot session
# started, who then only mutes/deafens without changing channel, could
# have their first real state-change event misread as a fresh "join"
# if GUILD_CREATE's voice_states seeding doesn't apply to them.
_last_channel: dict[tuple[str, str], Optional[str]] = {}

# Keyed by (guild_id, role_id): {"name": str, "permissions": int}. Roles
# are a small, slowly-changing dimension (bounded by how many roles
# exist across guilds this bot is in, not by distinct users), so unlike
# the caches above this doesn't need BoundedDict, just explicit cleanup
# on delete so it doesn't carry stale entries for roles that no longer
# exist.
_role_cache: dict[tuple[str, str], dict] = {}

# Keyed by (guild_id, user_id): frozenset of role_ids. This IS keyed by
# distinct users, so it uses BoundedDict from the start rather than
# repeating the mistake found (twice) elsewhere in this file's history.
_member_roles: "BoundedDict[tuple[str, str], frozenset]" = BoundedDict(max_size=10_000)

# Holds references to in-flight actor-lookup background tasks so they
# aren't garbage-collected mid-flight (asyncio only holds a weak
# reference to a task unless something else keeps it alive), each one
# removes itself once done, so this only ever holds currently-running
# lookups, not a growing history.
_background_tasks: set = set()


def _truncate(text: str, max_chars: int = 1000) -> str:
    text = text or ""
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jump_link(guild_id: str, channel_id: str, message_id: str) -> str:
    return f"{config.web_base}/channels/{guild_id}/{channel_id}/{message_id}"


async def _author_field(user_id: str, username: str, avatar_hash: Optional[str]) -> dict:
    field = {"name": f"{username} ({user_id})"}
    if avatar_hash:
        try:
            media_base = await get_media_base()
            icon = user_avatar_url(media_base, user_id, avatar_hash)
            if icon:
                field["icon_url"] = icon
        except Exception:
            pass  # cosmetic only, the log entry still goes out without an icon
    return field


async def _send_log(bot: Bot, channel_id: str, embed: dict) -> Optional[str]:
    """Returns the sent message's id (needed if a background actor lookup
    might want to edit it later), or None if sending failed."""
    try:
        result = await bot.rest.send_message(channel_id, embeds=[embed])
        return str(result["id"]) if result and result.get("id") else None
    except Exception:
        return None


async def _find_actor(bot: Bot, guild_id: str, action_type: int, target_id: str) -> Optional[dict]:
    try:
        audit = await bot.rest.get_audit_log(guild_id, action_type=action_type, limit=10)
        users_by_id = {str(u["id"]): u for u in audit.get("users", [])}
        for entry in audit.get("audit_log_entries", []):
            if str(entry.get("target_id")) == str(target_id):
                actor_id = str(entry.get("user_id", ""))
                return users_by_id.get(actor_id) or {"id": actor_id, "username": "unknown"}
    except Exception:
        log.debug("Audit log lookup failed for guild=%s action_type=%s", guild_id, action_type, exc_info=True)
    return None


def _spawn_actor_lookup(bot: Bot, guild_id: str, log_channel_id: str, message_id: Optional[str],
                         action_type: int, target_id: str, base_embed: dict) -> None:
    """Fire-and-forget: bot/client.py's gateway loop awaits every handler
    sequentially (see _dispatch), so blocking here for however long the
    audit log takes to populate and respond would stall ALL other event
    processing (messages, reactions, voice, everything) for that whole
    window. asyncio.create_task decouples this from the dispatch loop
    entirely, the base log entry has already gone out by the time this
    runs, this only ever adds a "Performed By" field a moment later."""
    if not message_id:
        return
    task = asyncio.create_task(_attach_actor(bot, guild_id, log_channel_id, message_id, action_type, target_id, base_embed))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _attach_actor(bot: Bot, guild_id: str, channel_id: str, message_id: str,
                         action_type: int, target_id: str, base_embed: dict) -> None:
    try:
        await asyncio.sleep(1.0)  # audit log entries can lag slightly behind the gateway event
        actor = await _find_actor(bot, guild_id, action_type, target_id)
        if not actor:
            return  # leave the entry as-is, the field's absence already communicates
                     # "couldn't determine who did this" without guessing
        embed = dict(base_embed)
        fields = list(embed.get("fields", []))
        fields.append({
            "name": "Performed By",
            "value": f"{actor.get('username', 'unknown')} ({actor.get('id', 'unknown')})",
            "inline": True,
        })
        embed["fields"] = fields
        await bot.rest.edit_message(channel_id, message_id, embeds=[embed])
    except Exception:
        pass  # cosmetic follow-up only, never let this crash anything


def register(bot: Bot) -> None:

    @bot.on("GUILD_CREATE")
    async def on_guild_create_seed(data: dict) -> None:
        guild_id = str(data.get("id"))
        for vs in data.get("voice_states", []) or []:
            user_id = vs.get("user_id")
            if user_id:
                _last_channel[(guild_id, str(user_id))] = str(vs["channel_id"]) if vs.get("channel_id") else None
        for role in data.get("roles", []) or []:
            role_id = role.get("id")
            if role_id:
                _role_cache[(guild_id, str(role_id))] = {
                    "name": role.get("name", "unknown"),
                    "permissions": int(role.get("permissions", 0)),
                }

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
            author_avatar=author.get("avatar"),
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

        jump = _jump_link(guild_id, cached["channel_id"], str(message_id))
        embed = {
            "title": "Message Edited",
            "color": 0xF5A623,
            "author": await _author_field(cached["author_id"], cached["author_username"], cached.get("author_avatar")),
            "fields": [
                {"name": "Before", "value": _truncate(cached["content"]) or "*(empty)*", "inline": False},
                {"name": "After", "value": _truncate(new_content) or "*(empty)*", "inline": False},
                {"name": "Channel", "value": f"<#{cached['channel_id']}>", "inline": True},
                {"name": "Jump to Message", "value": f"[Click here]({jump})", "inline": True},
            ],
            "footer": {"text": f"User ID: {cached['author_id']} • Message ID: {message_id}"},
            "timestamp": _now_iso(),
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
                "title": "Message Deleted",
                "color": 0xE0245E,
                "author": await _author_field(cached["author_id"], cached["author_username"], cached.get("author_avatar")),
                "fields": [
                    {"name": "Content", "value": _truncate(cached["content"]) or "*(empty)*", "inline": False},
                    {"name": "Channel", "value": f"<#{cached['channel_id']}>", "inline": True},
                ],
                "footer": {"text": f"User ID: {cached['author_id']} • Message ID: {message_id}"},
                "timestamp": _now_iso(),
            }
        else:
            channel_id = data.get("channel_id")
            embed = {
                "title": "Message Deleted",
                "color": 0xE0245E,
                "description": "Content not available (not cached during this bot session).",
                "fields": [{"name": "Channel", "value": f"<#{channel_id}>" if channel_id else "unknown", "inline": True}],
                "footer": {"text": f"Message ID: {message_id}"},
                "timestamp": _now_iso(),
            }
        await _send_log(bot, settings["log_channel_id"], embed)
        message_cache.forget(str(message_id))

    # ---------------------------------------------------------------- members --
    @bot.on("GUILD_MEMBER_ADD")
    async def on_member_add(data: dict) -> None:
        guild_id = data.get("guild_id")
        user = data.get("user", {})
        user_id = user.get("id")
        if not guild_id or not user_id:
            return
        _member_roles[(guild_id, str(user_id))] = frozenset(str(r) for r in data.get("roles", []) or [])

        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_member_joins"]:
            return
        if await db.is_ignored_log_user(guild_id, str(user_id)):
            return
        created_at = snowflake_to_datetime(str(user_id))
        embed = {
            "title": "Member Joined",
            "color": 0x4ADE80,
            "author": await _author_field(str(user_id), user.get("username", "unknown"), user.get("avatar")),
            "fields": [
                {"name": "Account Created", "value": format_date(created_at) if created_at else "unknown", "inline": True},
            ],
            "footer": {"text": f"User ID: {user_id}"},
            "timestamp": _now_iso(),
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    @bot.on("GUILD_MEMBER_REMOVE")
    async def on_member_remove(data: dict) -> None:
        guild_id = data.get("guild_id")
        user = data.get("user", {})
        user_id = user.get("id")
        if not guild_id or not user_id:
            return
        _member_roles.pop((guild_id, str(user_id)), None)

        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_member_leaves"]:
            return
        if await db.is_ignored_log_user(guild_id, str(user_id)):
            return
        embed = {
            "title": "Member Left",
            "color": 0xF16565,
            "author": await _author_field(str(user_id), user.get("username", "unknown"), user.get("avatar")),
            "footer": {"text": f"User ID: {user_id}"},
            "timestamp": _now_iso(),
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    @bot.on("GUILD_MEMBER_UPDATE")
    async def on_member_update(data: dict) -> None:
        guild_id = data.get("guild_id")
        user = data.get("user", {})
        user_id = user.get("id")
        if not guild_id or not user_id:
            return
        guild_id, user_id = str(guild_id), str(user_id)

        new_roles = frozenset(str(r) for r in data.get("roles", []) or [])
        key = (guild_id, user_id)
        old_roles = _member_roles.get(key)
        _member_roles[key] = new_roles
        if old_roles is None:
            return  # first time seeing this member's roles, nothing to diff against yet

        added, removed = new_roles - old_roles, old_roles - new_roles
        if not added and not removed:
            return  # something else about the member changed (nickname, etc.), not roles

        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_privileged_role_changes"]:
            return
        if await db.is_ignored_log_user(guild_id, user_id):
            return

        try:
            guild = await bot.get_guild(guild_id)
        except Exception:
            return  # can't evaluate which roles are privileged without the guild's role list
        privileged_added = [r for r in added if role_is_privileged(guild, r)]
        privileged_removed = [r for r in removed if role_is_privileged(guild, r)]
        if not privileged_added and not privileged_removed:
            return  # roles changed, but none of them carry elevated permissions, not logged

        fields = []
        if privileged_added:
            fields.append({"name": "Privileged Roles Added", "value": ", ".join(f"<@&{r}>" for r in privileged_added), "inline": False})
        if privileged_removed:
            fields.append({"name": "Privileged Roles Removed", "value": ", ".join(f"<@&{r}>" for r in privileged_removed), "inline": False})

        embed = {
            "title": "Privileged Role Change",
            "color": 0xF5A623 if (privileged_added and privileged_removed) else (0xE0245E if privileged_removed and not privileged_added else 0x4ADE80),
            "author": await _author_field(user_id, user.get("username", "unknown"), user.get("avatar")),
            "fields": fields,
            "footer": {"text": f"User ID: {user_id}"},
            "timestamp": _now_iso(),
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    # --------------------------------------------------------------- channels --
    @bot.on("CHANNEL_CREATE")
    async def on_channel_create(data: dict) -> None:
        guild_id = data.get("guild_id")
        channel_id = data.get("id")
        if not guild_id or not channel_id:
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_channel_changes"]:
            return
        embed = {
            "title": "Channel Created",
            "color": 0x4ADE80,
            "fields": [{"name": "Channel", "value": f"<#{channel_id}>", "inline": True}],
            "footer": {"text": f"Channel ID: {channel_id}"},
            "timestamp": _now_iso(),
        }
        message_id = await _send_log(bot, settings["log_channel_id"], embed)
        _spawn_actor_lookup(bot, guild_id, settings["log_channel_id"], message_id,
                             AUDIT_LOG_CHANNEL_CREATE, str(channel_id), embed)

    @bot.on("CHANNEL_DELETE")
    async def on_channel_delete(data: dict) -> None:
        guild_id = data.get("guild_id")
        channel_id = data.get("id")
        if not guild_id or not channel_id:
            return
        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_channel_changes"]:
            return
        # No mention here (unlike create/update): the channel is gone, and
        # an unresolvable <#id> mention renders as a broken/blank reference
        # in most clients rather than the last-known name. The plain name
        # from the event payload is what's actually still readable.
        embed = {
            "title": "Channel Deleted",
            "color": 0xE0245E,
            "fields": [{"name": "Name", "value": f"#{data.get('name', 'unknown')}", "inline": True}],
            "footer": {"text": f"Channel ID: {channel_id}"},
            "timestamp": _now_iso(),
        }
        message_id = await _send_log(bot, settings["log_channel_id"], embed)
        _spawn_actor_lookup(bot, guild_id, settings["log_channel_id"], message_id,
                             AUDIT_LOG_CHANNEL_DELETE, str(channel_id), embed)

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
            "title": "Channel Updated",
            "color": 0xF5A623,
            "fields": [{"name": "Channel", "value": f"<#{data.get('id')}>", "inline": True}],
            "footer": {"text": f"Channel ID: {data.get('id')}"},
            "timestamp": _now_iso(),
        }
        await _send_log(bot, settings["log_channel_id"], embed)

    # ------------------------------------------------------------------ roles --
    @bot.on("GUILD_ROLE_CREATE")
    async def on_role_create(data: dict) -> None:
        guild_id = data.get("guild_id")
        role = data.get("role", {})
        role_id = role.get("id")
        if not guild_id or not role_id:
            return
        perms = int(role.get("permissions", 0))
        _role_cache[(guild_id, str(role_id))] = {"name": role.get("name", "unknown"), "permissions": perms}

        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_role_changes"]:
            return
        perm_names = decode_permissions(perms)
        embed = {
            "title": "Role Created",
            "color": 0x4ADE80,
            "fields": [
                {"name": "Role", "value": f"<@&{role_id}>", "inline": True},
                {"name": "Permissions", "value": _truncate(", ".join(perm_names)) if perm_names else "None", "inline": False},
            ],
            "footer": {"text": f"Role ID: {role_id}"},
            "timestamp": _now_iso(),
        }
        message_id = await _send_log(bot, settings["log_channel_id"], embed)
        _spawn_actor_lookup(bot, guild_id, settings["log_channel_id"], message_id,
                             AUDIT_LOG_ROLE_CREATE, str(role_id), embed)

    @bot.on("GUILD_ROLE_DELETE")
    async def on_role_delete(data: dict) -> None:
        guild_id = data.get("guild_id")
        role_id = data.get("role_id")
        if not guild_id or not role_id:
            return
        _role_cache.pop((guild_id, str(role_id)), None)

        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_role_changes"]:
            return
        embed = {
            "title": "Role Deleted",
            "color": 0xE0245E,
            "footer": {"text": f"Role ID: {role_id}"},
            "timestamp": _now_iso(),
        }
        message_id = await _send_log(bot, settings["log_channel_id"], embed)
        _spawn_actor_lookup(bot, guild_id, settings["log_channel_id"], message_id,
                             AUDIT_LOG_ROLE_DELETE, str(role_id), embed)

    @bot.on("GUILD_ROLE_UPDATE")
    async def on_role_update(data: dict) -> None:
        guild_id = data.get("guild_id")
        role = data.get("role", {})
        role_id = role.get("id")
        if not guild_id or not role_id:
            return
        new_name = role.get("name", "unknown")
        new_perms = int(role.get("permissions", 0))
        cache_key = (guild_id, str(role_id))
        previous = _role_cache.get(cache_key)
        _role_cache[cache_key] = {"name": new_name, "permissions": new_perms}

        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_role_changes"]:
            return

        fields = [{"name": "Role", "value": f"<@&{role_id}>", "inline": True}]
        if previous:
            if previous["name"] != new_name:
                fields.append({"name": "Name", "value": f"{previous['name']} → {new_name}", "inline": False})
            old_perms = previous["permissions"]
            if old_perms != new_perms:
                added = decode_permissions(new_perms & ~old_perms)
                removed = decode_permissions(old_perms & ~new_perms)
                if added:
                    fields.append({"name": "Permissions Added", "value": _truncate(", ".join(added)), "inline": False})
                if removed:
                    fields.append({"name": "Permissions Removed", "value": _truncate(", ".join(removed)), "inline": False})
            if previous["name"] == new_name and old_perms == new_perms:
                return  # role "updated" but nothing we track actually changed (e.g. just color/icon)
        else:
            # No prior snapshot to diff against (bot started after this
            # role existed and never saw its create event), show the
            # current permission set instead of silently having nothing
            # to say about the update.
            perm_names = decode_permissions(new_perms)
            fields.append({"name": "Current Permissions", "value": _truncate(", ".join(perm_names)) if perm_names else "None", "inline": False})

        embed = {
            "title": "Role Updated",
            "color": 0xF5A623,
            "fields": fields,
            "footer": {"text": f"Role ID: {role_id}"},
            "timestamp": _now_iso(),
        }
        message_id = await _send_log(bot, settings["log_channel_id"], embed)
        _spawn_actor_lookup(bot, guild_id, settings["log_channel_id"], message_id,
                             AUDIT_LOG_ROLE_UPDATE, str(role_id), embed)

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
        if new_channel is None:
            # Otherwise this accumulates one permanent entry per distinct
            # user who's EVER touched voice. Nothing depends on retaining
            # this after a full disconnect: a future rejoin correctly
            # reports as a "join" either way, since a missing key and an
            # explicit None value behave identically through .get().
            _last_channel.pop(key, None)
        else:
            _last_channel[key] = new_channel

        if old_channel == new_channel:
            return  # a mute/deafen toggle, not a channel change

        settings = await db.get_activity_log_settings(guild_id)
        if not settings or not settings["log_channel_id"] or not settings["log_voice_activity"]:
            return
        if await db.is_ignored_log_user(guild_id, user_id):
            return

        try:
            member = await bot.get_member(guild_id, user_id, fresh=False)
            user_obj = member.get("user", member)
            username = user_obj.get("username", "unknown")
            avatar = user_obj.get("avatar")
        except Exception:
            username, avatar = "unknown", None
        author = await _author_field(user_id, username, avatar)

        if old_channel is None:
            title, color = "Joined Voice", 0x4ADE80
            fields = [{"name": "Channel", "value": f"<#{new_channel}>", "inline": True}]
        elif new_channel is None:
            title, color = "Left Voice", 0xF16565
            fields = [{"name": "Channel", "value": f"<#{old_channel}>", "inline": True}]
        else:
            title, color = "Switched Voice Channel", 0xF5A623
            fields = [
                {"name": "From", "value": f"<#{old_channel}>", "inline": True},
                {"name": "To", "value": f"<#{new_channel}>", "inline": True},
            ]

        embed = {
            "title": title, "color": color, "author": author, "fields": fields,
            "footer": {"text": f"User ID: {user_id}"}, "timestamp": _now_iso(),
        }
        await _send_log(bot, settings["log_channel_id"], embed)
