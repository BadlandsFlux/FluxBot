"""Reminders.

    !remind <duration> <text>    e.g. !remind 2h take out the trash
    !reminders                   list your pending reminders
    !delreminder <id>            cancel one
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.commands import Bot, Context
from bot.timeutil import parse_duration_seconds
from common import db

# No permission is required for !remind by design (it's a personal utility,
# not a moderation feature), which means bounding abuse has to happen some
# other way: without a cap, any member could spam short-duration reminders
# to grow the reminders table without limit and burst the scheduler's
# message-send calls (same bot token/rate-limit bucket as everything else)
# every time a batch comes due at once.
MAX_PENDING_REMINDERS_PER_USER = 10


def register(bot: Bot) -> None:

    @bot.command("remind", category="Utility", aliases=["reminder"],
                 help_text="Set a reminder. Usage: !remind <duration> <text>, e.g. !remind 2h take out trash")
    async def remind(ctx: Context) -> None:
        if len(ctx.args) < 2:
            await ctx.reply("Usage: `!remind <duration> <text>`, e.g. `!remind 2h take out trash`")
            return
        seconds = parse_duration_seconds(ctx.args[0])
        if seconds is None:
            await ctx.reply(f"Couldn't parse duration `{ctx.args[0]}`. Use e.g. `10m`, `2h`, `1d`.")
            return

        user_id = str(ctx.author["id"])
        pending = await db.count_pending_reminders(ctx.guild_id, user_id)
        if pending >= MAX_PENDING_REMINDERS_PER_USER:
            await ctx.reply(f"You already have {pending} pending reminders (the max is "
                             f"{MAX_PENDING_REMINDERS_PER_USER}). Cancel one with `!delreminder <id>` first.")
            return

        content = " ".join(ctx.args[1:])
        remind_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        reminder_id = await db.add_reminder(ctx.guild_id, ctx.channel_id, user_id, content, remind_at)
        await ctx.reply(f"⏰ Got it, I'll remind you in {ctx.args[0]}. (`#{reminder_id}`)")

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
