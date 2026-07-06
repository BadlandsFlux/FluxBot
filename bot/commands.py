"""A small prefix-command framework, deliberately simple.

Rather than depend on an undocumented cog/command API from a young
third-party wrapper, commands are plain async functions registered
against a shared `Bot` instance, dispatched from MESSAGE_CREATE. This
keeps the whole bot's behavior traceable to REST calls and gateway
events actually documented for Fluxer.
"""
from __future__ import annotations

import logging
import shlex
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from bot.client import GatewayClient
from bot.rest import FluxerREST, FluxerAPIError
from common.config import config

log = logging.getLogger("fluxbot.commands")

CommandFunc = Callable[["Context"], Awaitable[None]]
_PREFIX_CACHE_TTL = 30  # seconds
# Both of these back the permission check in _on_message (ctx.guild/ctx.member
# feed straight into is_moderator()). Without a TTL, a demoted moderator (role
# removed) or a role whose permissions get tightened keeps their old access
# for as long as the bot process stays up, since nothing else in this file
# forces a refetch. GUILD_UPDATE/GUILD_MEMBER_UPDATE invalidate these early
# when we see them, but the TTL is what actually guarantees an upper bound
# regardless of whether a given event fires or its shape matches what we
# expect (best-effort, Discord-convention assumption, like most event
# handling in this project).
_GUILD_CACHE_TTL = 60  # seconds
_MEMBER_CACHE_TTL = 60  # seconds


@dataclass
class Context:
    bot: "Bot"
    message: dict
    guild_id: str
    channel_id: str
    author: dict
    args: list[str]
    raw_args: str
    guild: Optional[dict] = None
    member: Optional[dict] = None

    async def reply(self, content: str) -> None:
        await self.bot.rest.send_message(self.channel_id, content=content)

    async def embed(self, title: str, description: str = "", color: int = 0x5865F2,
                     fields: Optional[list[dict]] = None) -> None:
        embed = {"title": title, "description": description, "color": color}
        if fields:
            embed["fields"] = fields
        await self.bot.rest.send_message(self.channel_id, embeds=[embed])


@dataclass
class Command:
    name: str
    func: CommandFunc
    aliases: list[str] = field(default_factory=list)
    required_permission: Optional[int] = None  # see bot.permissions
    help_text: str = ""
    category: str = "General"
    owner_only: bool = False


class Bot:
    def __init__(self, token: str):
        self.token = token
        self.rest = FluxerREST(token)
        self.gateway = GatewayClient(self.rest, token, config.intents)
        self.commands: dict[str, Command] = {}
        self.prefix = config.command_prefix
        self.started_at = time.monotonic()
        self._member_cache: dict[tuple[str, str], tuple[dict, float]] = {}
        self._guild_cache: dict[str, tuple[dict, float]] = {}
        self._prefix_cache: dict[str, tuple[str, float]] = {}  # guild_id -> (prefix, fetched_at)

        self.gateway.on("MESSAGE_CREATE")(self._on_message)

    # ------------------------------------------------------------- API --
    def command(self, name: str, aliases: Optional[list[str]] = None,
                required_permission: Optional[int] = None, help_text: str = "",
                category: str = "General", owner_only: bool = False):
        def deco(fn: CommandFunc) -> CommandFunc:
            cmd = Command(name=name, func=fn, aliases=aliases or [],
                           required_permission=required_permission, help_text=help_text,
                           category=category, owner_only=owner_only)
            self.commands[name] = cmd
            for alias in cmd.aliases:
                self.commands[alias] = cmd
            return fn
        return deco

    def on(self, event_name: str):
        return self.gateway.on(event_name)

    async def get_guild(self, guild_id: str, fresh: bool = False) -> dict:
        cached = self._guild_cache.get(guild_id)
        now = time.monotonic()
        if fresh or not cached or (now - cached[1]) >= _GUILD_CACHE_TTL:
            data = await self.rest.get_guild(guild_id)
            self._guild_cache[guild_id] = (data, now)
            return data
        return cached[0]

    async def get_member(self, guild_id: str, user_id: str, fresh: bool = False) -> dict:
        key = (guild_id, user_id)
        cached = self._member_cache.get(key)
        now = time.monotonic()
        if fresh or not cached or (now - cached[1]) >= _MEMBER_CACHE_TTL:
            data = await self.rest.get_guild_member(guild_id, user_id)
            self._member_cache[key] = (data, now)
            return data
        return cached[0]

    def invalidate_guild(self, guild_id: str) -> None:
        self._guild_cache.pop(guild_id, None)

    def invalidate_member(self, guild_id: str, user_id: str) -> None:
        self._member_cache.pop((guild_id, user_id), None)

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.started_at

    async def guild_count(self) -> int:
        from common import db
        return len(await db.list_guilds())

    async def get_prefix(self, guild_id: str) -> str:
        """Per-guild prefix, cached briefly so we're not hitting the DB on
        every message. Dashboard prefix changes take effect within
        _PREFIX_CACHE_TTL seconds."""
        cached = self._prefix_cache.get(guild_id)
        now = time.monotonic()
        if cached and (now - cached[1]) < _PREFIX_CACHE_TTL:
            return cached[0]
        from common import db
        guild_cfg = await db.get_guild(guild_id)
        prefix = guild_cfg["command_prefix"] if guild_cfg and guild_cfg["command_prefix"] else self.prefix
        self._prefix_cache[guild_id] = (prefix, now)
        return prefix

    # --------------------------------------------------------- internal --
    async def _on_message(self, data: dict) -> None:
        content: str = data.get("content", "") or ""
        author = data.get("author", {})
        if author.get("bot"):
            return
        guild_id = data.get("guild_id")
        if not guild_id:
            return  # DMs not handled by a moderation bot

        prefix = await self.get_prefix(guild_id)
        if not content.startswith(prefix):
            return

        body = content[len(prefix):].strip()
        if not body:
            return
        try:
            parts = shlex.split(body)
        except ValueError:
            parts = body.split()
        if not parts:
            return
        name, args = parts[0].lower(), parts[1:]
        command = self.commands.get(name)
        channel_id = data.get("channel_id")
        if not command:
            from common import db
            tag_row = await db.get_tag(guild_id, name)
            if tag_row:
                try:
                    await self.rest.send_message(channel_id, content=tag_row["content"])
                except Exception:
                    log.warning("Failed to send tag %s in guild %s", name, guild_id)
            return

        ctx = Context(
            bot=self, message=data, guild_id=guild_id, channel_id=channel_id,
            author=author, args=args, raw_args=body[len(parts[0]):].strip(),
        )

        if command.owner_only:
            if not config.owner_id or str(author.get("id")) != config.owner_id:
                await ctx.reply("That command is restricted to the bot owner.")
                return
            try:
                await command.func(ctx)
            except Exception:
                log.exception("Command %s raised an unexpected error", name)
                await ctx.reply("Something went wrong running that command.")
            return

        try:
            ctx.guild = await self.get_guild(guild_id)
            ctx.member = await self.get_member(guild_id, author.get("id"))
        except FluxerAPIError as e:
            log.warning("Failed to fetch guild/member context: %s", e)
            return

        if command.required_permission is not None:
            from bot.permissions import is_moderator
            if not is_moderator(ctx.guild, ctx.member, command.required_permission):
                await ctx.reply("You don't have permission to use that command.")
                return

        try:
            await command.func(ctx)
        except FluxerAPIError as e:
            log.warning("Command %s failed: %s", name, e)
            await ctx.reply(f"That didn't work — the Fluxer API said: `{e.status}`. "
                             f"(Check the bot's permissions / role position.)")
        except Exception:
            log.exception("Command %s raised an unexpected error", name)
            await ctx.reply("Something went wrong running that command.")

    async def start(self) -> None:
        await self.rest.start()
        await self.gateway.run_forever()

    async def close(self) -> None:
        self.gateway.stop()
        await self.rest.close()
