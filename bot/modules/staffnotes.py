"""Staff notes.

Private context moderators can leave on a member, distinct from the
warning system, no escalation, just visibility for staff (e.g. "was
rude in DMs, keep an eye on this one"). Gated at the same trust level
as !warn.

    !note add @user <text>
    !note list @user
    !note remove <note_id>
"""
from __future__ import annotations

from bot.commands import Bot, Context
from bot.modules.moderation import parse_id
from bot.permissions import PERM_KICK_MEMBERS
from common import db


def register(bot: Bot) -> None:

    @bot.command("note", category="Moderation", required_permission=PERM_KICK_MEMBERS,
                 help_text="Private staff notes on a member. Usage: !note add/list/remove ...")
    async def note(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Usage: `!note add @user <text>`, `!note list @user`, or `!note remove <id>`")
            return

        sub = ctx.args[0].lower()

        if sub == "add":
            if len(ctx.args) < 3:
                await ctx.reply("Usage: `!note add @user <text>`")
                return
            target_id = parse_id(ctx.args[1])
            if not target_id:
                await ctx.reply(f"Couldn't parse `{ctx.args[1]}` as a user.")
                return
            text = " ".join(ctx.args[2:])
            note_id = await db.add_staff_note(ctx.guild_id, target_id, text, str(ctx.author["id"]))
            await ctx.reply(f"📝 Noted. (`#{note_id}`)")
            return

        if sub == "list":
            if len(ctx.args) < 2:
                await ctx.reply("Usage: `!note list @user`")
                return
            target_id = parse_id(ctx.args[1])
            if not target_id:
                await ctx.reply(f"Couldn't parse `{ctx.args[1]}` as a user.")
                return
            rows = await db.list_staff_notes(ctx.guild_id, target_id)
            if not rows:
                await ctx.reply("No notes on that member.")
                return
            lines = [f"`#{r['id']}` by <@{r['created_by']}>: {r['note']}" for r in rows[:15]]
            await ctx.embed(f"Staff notes for <@{target_id}>", "\n".join(lines))
            return

        if sub == "remove":
            if len(ctx.args) < 2 or not ctx.args[1].lstrip("#").isdigit():
                await ctx.reply("Usage: `!note remove <id>` (see `!note list @user` for IDs)")
                return
            note_id = int(ctx.args[1].lstrip("#"))
            removed = await db.remove_staff_note(ctx.guild_id, note_id)
            await ctx.reply("✅ Removed." if removed else "No note with that ID.")
            return

        await ctx.reply("Usage: `!note add @user <text>`, `!note list @user`, or `!note remove <id>`")
