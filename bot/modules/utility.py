"""Utility commands: !help, !ping."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from bot.bounded_cache import BoundedDict
from bot.commands import Bot, Context
from bot.permissions import is_moderator, permission_name
from bot.timeutil import format_duration
from common import db
from common.config import config

CATEGORY_ORDER = ["Moderation", "Roles", "Info", "Fun", "Utility", "General"]
CATEGORY_EMOJI = {
    "Moderation": "🛡️", "Roles": "🎭", "Info": "ℹ️",
    "Fun": "🎉", "Utility": "🔧", "General": "📎",
}
EMBED_FIELD_VALUE_LIMIT = 1024
HELP_PREV_EMOJI = "⬅️"
HELP_NEXT_EMOJI = "➡️"
_MAX_HELP_SESSIONS = 500  # bounded: one entry per outstanding paginated !help message


@dataclass
class _HelpSession:
    user_id: str
    channel_id: str
    pages: list[dict] = field(default_factory=list)
    page: int = 0


# Evicted (oldest-first) past _MAX_HELP_SESSIONS: a miss just means the nav
# reactions on a very old/inactive !help message stop doing anything,
# nothing a guild would notice in practice.
_help_sessions: "BoundedDict[str, _HelpSession]" = BoundedDict(max_size=_MAX_HELP_SESSIONS)


def _chunk_field_value(lines: list[str], limit: int = EMBED_FIELD_VALUE_LIMIT) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        added_len = len(line) + (1 if current else 0)
        if current and current_len + added_len > limit:
            chunks.append("\n".join(current))
            current, current_len = [line], len(line)
        else:
            current.append(line)
            current_len += added_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def _visible_commands(bot: Bot, guild: dict, member: dict, author_id: str) -> list:
    """Every distinct command the invoking member can actually run: owner-only
    commands only for the configured bot owner, permission-gated commands
    only if is_moderator() says this member's roles clear that bit, same
    checks _on_message itself enforces before running a command."""
    seen = set()
    visible = []
    for cmd in bot.commands.values():
        if cmd.name in seen:
            continue
        seen.add(cmd.name)
        if cmd.owner_only:
            if not config.owner_id or str(author_id) != config.owner_id:
                continue
        elif cmd.required_permission is not None:
            if not is_moderator(guild, member, cmd.required_permission):
                continue
        visible.append(cmd)
    return visible


def _build_help_pages(prefix: str, commands: list) -> list[dict]:
    """One embed page per command category, each already safe under
    Discord/Fluxer's per-field (1024 char) limit via _chunk_field_value."""
    by_category: dict[str, list] = {}
    for cmd in commands:
        by_category.setdefault(cmd.category, []).append(cmd)

    categories = [c for c in CATEGORY_ORDER if c in by_category]
    categories += [c for c in by_category if c not in categories]

    pages = []
    for category in categories:
        cmds = sorted(by_category[category], key=lambda c: c.name)
        lines = []
        for cmd in cmds:
            perm = permission_name(cmd.required_permission)
            perm_note = "" if perm == "Everyone" else f"  ·  _{perm}_"
            if cmd.owner_only:
                perm_note = "  ·  _Owner only_"
            lines.append(f"**`{prefix}{cmd.name}`** — {cmd.help_text or 'No description.'}{perm_note}")
        emoji = CATEGORY_EMOJI.get(category, "•")
        fields = [
            {"name": f"{emoji} {category}" if i == 0 else f"{emoji} {category} (cont.)",
             "value": chunk, "inline": False}
            for i, chunk in enumerate(_chunk_field_value(lines))
        ]
        pages.append({
            "title": f"{config.bot_name} commands",
            "description": f"Prefix for this server: `{prefix}`",
            "color": 0x5865F2,
            "fields": fields,
        })

    if len(pages) > 1:
        for embed in pages:
            embed["description"] += f"\nReact with {HELP_PREV_EMOJI} {HELP_NEXT_EMOJI} to see other pages."
    for i, embed in enumerate(pages):
        embed["footer"] = {"text": f"Page {i + 1}/{len(pages)} · showing commands you can use"}
    return pages


def register(bot: Bot) -> None:

    @bot.command("ping", category="Utility",
                 help_text="Show latency, uptime, and other live stats. Usage: !ping")
    async def ping(ctx: Context) -> None:
        api_start = time.monotonic()
        sent = await ctx.bot.rest.send_message(ctx.channel_id, content="🏓 Pinging...")
        api_latency_ms = (time.monotonic() - api_start) * 1000

        db_start = time.monotonic()
        try:
            await db.get_guild(ctx.guild_id)
            db_status = f"{(time.monotonic() - db_start) * 1000:.0f}ms"
        except Exception:
            db_status = "unreachable"

        gw_latency = ctx.bot.gateway.latency_ms
        gw_status = f"{gw_latency:.0f}ms" if gw_latency is not None else "warming up…"

        guild_count = await ctx.bot.guild_count()
        uptime = format_duration(ctx.bot.uptime_seconds)

        embed = {
            "title": f"🏓 {config.bot_name} status",
            "color": 0x5865F2,
            "fields": [
                {"name": "Gateway latency", "value": gw_status, "inline": True},
                {"name": "API latency", "value": f"{api_latency_ms:.0f}ms", "inline": True},
                {"name": "Database latency", "value": db_status, "inline": True},
                {"name": "Uptime", "value": uptime, "inline": True},
                {"name": "Servers", "value": str(guild_count), "inline": True},
                {"name": "Commands loaded", "value": str(len(set(c.name for c in bot.commands.values()))),
                 "inline": True},
            ],
        }
        try:
            await ctx.bot.rest.edit_message(ctx.channel_id, str(sent["id"]), content="", embeds=[embed])
        except Exception:
            await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])

    @bot.command("help", category="Utility", help_text="List commands. Usage: !help")
    async def help_cmd(ctx: Context) -> None:
        prefix = await ctx.bot.get_prefix(ctx.guild_id)
        visible = _visible_commands(bot, ctx.guild or {}, ctx.member or {}, ctx.author.get("id"))
        if not visible:
            await ctx.reply("No commands are available to you in this server.")
            return
        pages = _build_help_pages(prefix, visible)

        sent = await ctx.bot.rest.send_message(ctx.channel_id, embeds=[pages[0]])
        if len(pages) > 1:
            message_id = str(sent["id"])
            _help_sessions[message_id] = _HelpSession(
                user_id=str(ctx.author.get("id")), channel_id=ctx.channel_id, pages=pages,
            )
            try:
                await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, HELP_PREV_EMOJI)
                await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, HELP_NEXT_EMOJI)
            except Exception:
                pass  # the help text itself already sent fine; paging just won't be clickable

    @bot.on("MESSAGE_REACTION_ADD")
    async def on_help_page_reaction(data: dict) -> None:
        message_id = str(data.get("message_id"))
        session = _help_sessions.get(message_id)
        if not session:
            return

        emoji_data = data.get("emoji", {})
        emoji = emoji_data.get("name") if isinstance(emoji_data, dict) else emoji_data
        if emoji not in (HELP_PREV_EMOJI, HELP_NEXT_EMOJI):
            return

        user_id = str(data.get("user_id"))
        bot_user_id = (bot.gateway.user or {}).get("id")
        if bot_user_id and user_id == str(bot_user_id):
            return  # our own nav reactions added when the page was sent
        if user_id != session.user_id:
            return  # someone else's !help is scoped to their own permissions, not this viewer's

        step = -1 if emoji == HELP_PREV_EMOJI else 1
        session.page = (session.page + step) % len(session.pages)
        try:
            await bot.rest.edit_message(session.channel_id, message_id, content="",
                                         embeds=[session.pages[session.page]])
        except Exception:
            return
        try:
            await bot.rest.remove_user_reaction(session.channel_id, message_id, emoji, user_id)
        except Exception:
            pass  # bot likely lacks Manage Messages; paging still works, just can't re-click instantly
