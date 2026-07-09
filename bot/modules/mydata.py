"""Personal data transparency.

    !mydata    everything the bot has stored about you in this server:
                messages sent, voice time, XP/level, achievements,
                warnings (active and cleared), AFK status if
                currently set. DMs it by default (this can include
                warning history, not something to broadcast into a
                public channel), falls back to replying in-channel
                only if your DMs are closed, with a note that it did.

Deliberately excludes staff notes. Those exist specifically for
private moderator context ("was rude in DMs, keep an eye on this
one"), and showing them to the subject would defeat the entire
purpose of the feature, staff notes are meant to be quiet, ongoing
context, not something the person being watched can read and react
to. This is a considered exclusion, not an oversight.

Self-only by design: no @user argument. The point is transparency
about YOUR OWN data, not a lookup tool for checking on someone else,
the Members tab and !note already cover that for people who actually
have the permission to.
"""
from __future__ import annotations

from bot.commands import Bot, Context
from bot.modules.achievements import ACHIEVEMENTS
from bot.rest import FluxerAPIError
from common import db


def register(bot: Bot) -> None:

    @bot.command("mydata", category="Info",
                 help_text="See everything the bot has stored about you in this server. Usage: !mydata")
    async def mydata(ctx: Context) -> None:
        user_id = str(ctx.author["id"])
        guild_id = ctx.guild_id

        message_count = await db.get_member_message_count(guild_id, user_id)
        voice_minutes = await db.get_member_voice_minutes(guild_id, user_id)
        level_row = await db.get_level(guild_id, user_id)
        earned_achievements = await db.list_achievements(guild_id, user_id)
        warnings = await db.list_warnings(guild_id, user_id)
        afk_row = await db.get_afk(guild_id, user_id)

        lines = [
            f"**Messages sent:** {message_count:,}",
            f"**Voice time:** {voice_minutes / 60:.1f}h",
            f"**Level:** {level_row['level']} ({level_row['xp']:,} XP)" if level_row else "**Level:** no XP earned yet",
        ]

        if earned_achievements:
            names = [ACHIEVEMENTS.get(a["key"], {}).get("name", a["key"]) for a in earned_achievements]
            lines.append(f"**Achievements ({len(names)}/{len(ACHIEVEMENTS)}):** {', '.join(names)}")
        else:
            lines.append(f"**Achievements (0/{len(ACHIEVEMENTS)}):** none yet")

        active = [w for w in warnings if w["active"]]
        if warnings:
            lines.append(f"**Warnings:** {len(active)} active, {len(warnings)} total (including cleared)")
            for w in warnings[:10]:
                status = "active" if w["active"] else "cleared"
                lines.append(f"　`{w['created_at'].strftime('%Y-%m-%d')}` ({status}): {w['reason']}")
            if len(warnings) > 10:
                lines.append(f"　...and {len(warnings) - 10} more")
        else:
            lines.append("**Warnings:** none")

        if afk_row:
            lines.append(f"**Currently AFK:** {afk_row['reason']}")

        lines.append("")
        lines.append("Staff notes (if any exist on you) aren't included here, those are private "
                      "moderator context, not part of what this command shows.")

        embed = {"title": "Your data on this server", "color": 0x5865F2, "description": "\n".join(lines)}

        try:
            dm = await ctx.bot.rest.create_dm(user_id)
            await ctx.bot.rest.send_message(dm["id"], embeds=[embed])
            await ctx.reply("📬 Sent you a DM with your data.")
        except FluxerAPIError:
            await ctx.reply("Couldn't DM you (check that DMs from server members are allowed), "
                             "posting here instead:")
            await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])
