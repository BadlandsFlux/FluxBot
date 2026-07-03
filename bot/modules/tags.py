"""Custom tags — server-defined shortcuts.

    !tag add <name> <content>
    !tag remove <name>
    !tag list

Once added, invoking the tag by its own name (e.g. `!rules` for a tag
named "rules") posts its content — handled as a fallback in
bot/commands.py's dispatcher when no built-in command matches.
"""
from __future__ import annotations

from bot.commands import Bot, Context
from bot.permissions import PERM_MANAGE_GUILD, is_moderator
from common import db


def register(bot: Bot) -> None:

    @bot.command("tag", category="Utility",
                 help_text="Manage custom tags. Usage: !tag add <name> <content> / remove <name> / list")
    async def tag(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Usage: `!tag add <name> <content>` / `remove <name>` / `list`")
            return
        sub = ctx.args[0].lower()

        if sub == "list":
            rows = await db.list_tags(ctx.guild_id)
            if not rows:
                await ctx.reply("No tags set yet. Add one with `!tag add <name> <content>`.")
                return
            names = ", ".join(f"`{r['name']}`" for r in rows)
            await ctx.embed("Tags", names)
            return

        if sub == "add":
            if not is_moderator(ctx.guild, ctx.member, PERM_MANAGE_GUILD):
                await ctx.reply("You need Manage Guild permission to add tags.")
                return
            if len(ctx.args) < 3:
                await ctx.reply("Usage: `!tag add <name> <content>`")
                return
            name = ctx.args[1].lower()
            if bot.commands.get(name):
                await ctx.reply(f"`{name}` is already a built-in command name — pick another.")
                return
            # raw_args is "add <name> <content...>" — split off the first two tokens.
            parts = ctx.raw_args.split(" ", 2)
            content = parts[2] if len(parts) > 2 else ""
            if not content:
                await ctx.reply("Give some content for the tag.")
                return
            await db.add_tag(ctx.guild_id, name, content, str(ctx.author["id"]))
            await ctx.reply(f"✅ Saved tag `{name}`.")
            return

        if sub == "remove":
            if not is_moderator(ctx.guild, ctx.member, PERM_MANAGE_GUILD):
                await ctx.reply("You need Manage Guild permission to remove tags.")
                return
            if len(ctx.args) < 2:
                await ctx.reply("Usage: `!tag remove <name>`")
                return
            removed = await db.remove_tag(ctx.guild_id, ctx.args[1])
            await ctx.reply(f"✅ Removed tag `{ctx.args[1].lower()}`." if removed else "No tag with that name.")
            return

        await ctx.reply("Usage: `!tag add <name> <content>` / `remove <name>` / `list`")
