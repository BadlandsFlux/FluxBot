"""Per-command enable/disable.

    !commands list                 show which commands are disabled here
    !commands disable <name>
    !commands enable <name>

Disabling is per-guild and keyed by a command's canonical name, so
disabling it blocks every alias too. A couple of commands (this one,
and !help) can never be disabled, so a server can't lock itself out
of managing or discovering commands from chat. The dashboard has the
same toggle under a guild's settings.
"""
from __future__ import annotations

from bot.commands import Bot, Context, NEVER_DISABLED_COMMANDS
from bot.permissions import PERM_MANAGE_GUILD
from common import db


def register(bot: Bot) -> None:

    @bot.command("commands", category="Utility", aliases=["command"], required_permission=PERM_MANAGE_GUILD,
                 help_text="Enable/disable commands for this server. "
                            "Usage: !commands list / enable <name> / disable <name>")
    async def commands_cmd(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Usage: `!commands list` / `enable <name>` / `disable <name>`")
            return
        sub = ctx.args[0].lower()

        if sub == "list":
            disabled = sorted(await db.list_disabled_commands(ctx.guild_id))
            if not disabled:
                await ctx.reply("No commands are disabled in this server.")
                return
            await ctx.reply("Disabled commands: " + ", ".join(f"`{name}`" for name in disabled))
            return

        if sub not in ("enable", "disable") or len(ctx.args) < 2:
            await ctx.reply("Usage: `!commands list` / `enable <name>` / `disable <name>`")
            return

        target_name = ctx.args[1].lower()
        command = ctx.bot.commands.get(target_name)
        if not command:
            await ctx.reply(f"No command named `{target_name}`.")
            return
        if command.owner_only or command.name in NEVER_DISABLED_COMMANDS:
            await ctx.reply(f"`{command.name}` can't be disabled.")
            return

        if sub == "disable":
            await db.disable_command(ctx.guild_id, command.name)
            await ctx.reply(f"🚫 `{command.name}` is now disabled in this server.")
        else:
            await db.enable_command(ctx.guild_id, command.name)
            await ctx.reply(f"✅ `{command.name}` is enabled again.")
