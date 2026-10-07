"""Chat-based settings fallback.

    !settings                     show the current prefix + a dashboard pointer
    !settings prefix               show the current prefix
    !settings prefix <new>         change it (max 5 characters)
    !settings prefix reset         reset it back to the default

Most server settings (welcome/goodbye messages, leveling, warn
thresholds, log channels, and so on) only have an editor in the
dashboard. This command covers the one setting admins most often need
to change without switching to a browser; everything else still
points there.
"""
from __future__ import annotations

from bot.commands import Bot, Context
from bot.permissions import PERM_MANAGE_GUILD
from common import db
from common.config import config


def register(bot: Bot) -> None:

    @bot.command("settings", category="Utility", aliases=["config"], required_permission=PERM_MANAGE_GUILD,
                 help_text="View or change the command prefix from chat. Usage: !settings prefix [<new>|reset]")
    async def settings_cmd(ctx: Context) -> None:
        if not ctx.args:
            prefix = await ctx.bot.get_prefix(ctx.guild_id)
            await ctx.embed(
                "⚙️ Server settings",
                f"**Prefix:** `{prefix}`\n\n"
                f"Use `{prefix}settings prefix <new>` to change it. Everything else (welcome/goodbye "
                f"messages, leveling, warn thresholds, logging, and more) is configured from the dashboard.",
            )
            return

        if ctx.args[0].lower() != "prefix":
            await ctx.reply("Usage: `!settings prefix [<new>|reset]`")
            return

        if len(ctx.args) < 2:
            prefix = await ctx.bot.get_prefix(ctx.guild_id)
            await ctx.reply(f"Current prefix: `{prefix}`")
            return

        if ctx.args[1].lower() == "reset":
            new_prefix = config.command_prefix
        else:
            new_prefix = ctx.args[1].strip()[:5]
            if not new_prefix:
                await ctx.reply("That prefix can't be blank.")
                return

        await db.update_guild_settings(ctx.guild_id, command_prefix=new_prefix)
        ctx.bot.invalidate_prefix(ctx.guild_id)
        await ctx.reply(f"✅ Prefix set to `{new_prefix}`.")
