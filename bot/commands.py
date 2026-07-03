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
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from bot.client import GatewayClient
from bot.rest import FluxerREST, FluxerAPIError
from common.config import config

log = logging.getLogger("fluxerbot.commands")

CommandFunc = Callable[["Context"], Awaitable[None]]


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


class Bot:
    def __init__(self, token: str):
        self.token = token
        self.rest = FluxerREST(token)
        self.gateway = GatewayClient(self.rest, token, config.intents)
        self.commands: dict[str, Command] = {}
        self.prefix = config.command_prefix
        self._member_cache: dict[tuple[str, str], dict] = {}
        self._guild_cache: dict[str, dict] = {}

        self.gateway.on("MESSAGE_CREATE")(self._on_message)

    # ------------------------------------------------------------- API --
    def command(self, name: str, aliases: Optional[list[str]] = None,
                required_permission: Optional[int] = None, help_text: str = ""):
        def deco(fn: CommandFunc) -> CommandFunc:
            cmd = Command(name=name, func=fn, aliases=aliases or [],
                           required_permission=required_permission, help_text=help_text)
            self.commands[name] = cmd
            for alias in cmd.aliases:
                self.commands[alias] = cmd
            return fn
        return deco

    def on(self, event_name: str):
        return self.gateway.on(event_name)

    async def get_guild(self, guild_id: str, fresh: bool = False) -> dict:
        if fresh or guild_id not in self._guild_cache:
            self._guild_cache[guild_id] = await self.rest.get_guild(guild_id)
        return self._guild_cache[guild_id]

    async def get_member(self, guild_id: str, user_id: str, fresh: bool = False) -> dict:
        key = (guild_id, user_id)
        if fresh or key not in self._member_cache:
            self._member_cache[key] = await self.rest.get_guild_member(guild_id, user_id)
        return self._member_cache[key]

    def invalidate_guild(self, guild_id: str) -> None:
        self._guild_cache.pop(guild_id, None)

    # --------------------------------------------------------- internal --
    async def _on_message(self, data: dict) -> None:
        content: str = data.get("content", "") or ""
        author = data.get("author", {})
        if author.get("bot"):
            return
        if not content.startswith(self.prefix):
            return
        guild_id = data.get("guild_id")
        if not guild_id:
            return  # DMs not handled by a moderation bot

        body = content[len(self.prefix):].strip()
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
        if not command:
            return

        channel_id = data.get("channel_id")
        ctx = Context(
            bot=self, message=data, guild_id=guild_id, channel_id=channel_id,
            author=author, args=args, raw_args=body[len(parts[0]):].strip(),
        )

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
