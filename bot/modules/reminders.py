"""Reminders.

    !remind <when> <text>    e.g. !remind in 2 hours take out the trash,
                                   !remind tomorrow at 3pm check the oven,
                                   or the older !remind 2h take out the trash
    !reminders                list your pending reminders
    !delreminder <id>         cancel one
"""
from __future__ import annotations

from datetime import datetime, timezone

from bot.commands import Bot, Context
from bot.timeutil import parse_natural_time
from common import db

# No permission is required for !remind by design (it's a personal utility,
# not a moderation feature), which means bounding abuse has to happen some
# other way: without a cap, any member could spam short-duration reminders
# to grow the reminders table without limit and burst the scheduler's
# message-send calls (same bot token/rate-limit bucket as everything else)
# every time a batch comes due at once.
MAX_PENDING_REMINDERS_PER_USER = 10

REMIND_USAGE = ("Usage: `!remind <when> <text>`, e.g. `!remind in 2 hours take out the trash` "
                "or `!remind tomorrow at 3pm check the oven` (the older `!remind 2h take out the trash` "
                "still works too).")


def register(bot: Bot) -> None:

    @bot.command("remind", category="Utility", aliases=["reminder"],
                 help_text="Set a reminder using natural language. "
                            "Usage: !remind <when> <text>, e.g. !remind in 2 hours take out the trash")
    async def remind(ctx: Context) -> None:
        if not ctx.raw_args:
            await ctx.reply(REMIND_USAGE)
            return
        parsed = parse_natural_time(ctx.raw_args)
        if parsed is None:
            await ctx.reply(f"Couldn't find both a time and a message in that. {REMIND_USAGE}")
            return
        remind_at, content = parsed
        now = datetime.now(timezone.utc)
        if remind_at <= now:
            await ctx.reply(f"That works out to <t:{int(remind_at.timestamp())}>, which is in the past. "
                             f"Give me a time in the future.")
            return

        user_id = str(ctx.author["id"])
        pending = await db.count_pending_reminders(ctx.guild_id, user_id)
        if pending >= MAX_PENDING_REMINDERS_PER_USER:
            await ctx.reply(f"You already have {pending} pending reminders (the max is "
                             f"{MAX_PENDING_REMINDERS_PER_USER}). Cancel one with `!delreminder <id>` first.")
            return

        reminder_id = await db.add_reminder(ctx.guild_id, ctx.channel_id, user_id, content, remind_at)
        await ctx.reply(f"⏰ Got it, I'll remind you <t:{int(remind_at.timestamp())}:R>. (`#{reminder_id}`)")

    @bot.command("reminders", category="Utility", help_text="List your pending reminders. Usage: !reminders")
    async def reminders_cmd(ctx: Context) -> None:
        rows = await db.list_reminders_for_user(ctx.guild_id, str(ctx.author["id"]))
        if not rows:
            await ctx.reply("You have no pending reminders.")
            return
        lines = [f"`#{r['id']}` <t:{int(r['remind_at'].timestamp())}> — {r['content']}" for r in rows[:10]]
        await ctx.embed("Your reminders", "\n".join(lines))

    @bot.command("delreminder", category="Utility", aliases=["cancelreminder"],
                 help_text="Cancel a reminder. Usage: !delreminder <id>")
    async def del_reminder(ctx: Context) -> None:
        if not ctx.args or not ctx.args[0].lstrip("#").isdigit():
            await ctx.reply("Usage: `!delreminder <id>` (see `!reminders` for IDs)")
            return
        reminder_id = int(ctx.args[0].lstrip("#"))
        removed = await db.remove_reminder(reminder_id, str(ctx.author["id"]))
        await ctx.reply("✅ Cancelled." if removed else "No reminder with that ID (or it isn't yours).")
