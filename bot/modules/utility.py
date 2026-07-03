"""Utility commands: !help, !ping."""
from __future__ import annotations

import time

from bot.commands import Bot, Context


def register(bot: Bot) -> None:

    @bot.command("ping", help_text="Check the bot is alive. Usage: !ping")
    async def ping(ctx: Context) -> None:
        await ctx.reply("🏓 Pong!")

    @bot.command("help", help_text="List commands. Usage: !help")
    async def help_cmd(ctx: Context) -> None:
        seen = set()
        lines = []
        for cmd in bot.commands.values():
            if cmd.name in seen:
                continue
            seen.add(cmd.name)
            alias_txt = f" (aliases: {', '.join(cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"**{bot.prefix}{cmd.name}**{alias_txt} — {cmd.help_text}")
        lines.sort()
        await ctx.embed("Commands", "\n".join(lines))
