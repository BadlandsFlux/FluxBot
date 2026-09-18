"""Self-service Discord <-> Fluxer account linking.

    !link          start a link: DMs you a short code, good for 10 minutes.
                    Finish it on Discord by DMing this bot's Discord relay
                    `!link <code>` (see bot/discord_relay.py's DM handling).
    !unlink        remove your account link.
    !linkstatus    show whether you're currently linked.

Why a code exchange rather than just typing in the other platform's ID:
anyone can see another member's Discord or Fluxer id, it's not a secret,
so accepting a bare id would let someone link (and start getting live-
pinged as) an account that isn't theirs. A short-lived, single-use code
DMed to the account making the claim is proof of control over it, the
same trust model as an email verification link or a 2FA backup code.

Once linked, a `<@user>` mention in a bridged channel translates into a
real, clickable, notifying mention on the OTHER platform (instead of
today's plain "@username" text) whenever the linked account is actually
a member of the destination channel/guild, see bot/discord_relay.py's
live-mention resolution for the other half of this feature.
"""
from __future__ import annotations

from bot.commands import Bot, Context
from bot.rest import FluxerAPIError
from common import db


def register(bot: Bot) -> None:

    @bot.command("link", category="Utility",
                 help_text="Link your Discord and Fluxer accounts so pings translate between them. Usage: !link")
    async def link(ctx: Context) -> None:
        user_id = str(ctx.author["id"])
        existing = await db.get_link_by_fluxer(user_id)
        code = await db.create_link_code(user_id)
        embed = {
            "title": "🔗 Link your Discord account",
            "color": 0x5865F2,
            "description": (
                f"Your code: **`{code}`**\n\n"
                "On Discord, send this bot's relay a DM: `!link " + code + "`\n\n"
                "Good for 10 minutes. Starting a new `!link` cancels this code."
            ),
        }
        if existing:
            embed["description"] += "\n\nThis replaces your current link."

        try:
            dm = await ctx.bot.rest.create_dm(user_id)
            await ctx.bot.rest.send_message(dm["id"], embeds=[embed])
            await ctx.reply("📬 Sent you a DM with your linking code.")
        except FluxerAPIError:
            await ctx.reply("Couldn't DM you (check that DMs from server members are allowed), "
                             "posting here instead, you may want to delete this after:")
            await ctx.bot.rest.send_message(ctx.channel_id, embeds=[embed])

    @bot.command("unlink", category="Utility",
                 help_text="Remove your Discord/Fluxer account link. Usage: !unlink")
    async def unlink(ctx: Context) -> None:
        user_id = str(ctx.author["id"])
        removed = await db.remove_link_by_fluxer(user_id)
        if removed:
            await ctx.reply("🔓 Unlinked. Pings between Discord and Fluxer for your account will go back "
                             "to plain text.")
        else:
            await ctx.reply("You don't have an account linked right now.")

    @bot.command("linkstatus", category="Utility", aliases=["linked"],
                 help_text="Show whether your Discord/Fluxer accounts are linked. Usage: !linkstatus")
    async def linkstatus(ctx: Context) -> None:
        user_id = str(ctx.author["id"])
        link_row = await db.get_link_by_fluxer(user_id)
        if not link_row:
            await ctx.reply("Not linked. Run `!link` to start.")
            return
        await ctx.reply(
            f"🔗 Linked to Discord user `{link_row['discord_user_id']}` "
            f"(mention them on Discord as `<@{link_row['discord_user_id']}>` to check who that is) "
            f"since {link_row['linked_at'].strftime('%Y-%m-%d')}."
        )
