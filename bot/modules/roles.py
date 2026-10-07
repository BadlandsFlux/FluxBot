"""Autorole + reaction roles.

    !autorole add @role                 role auto-assigned to every new member
    !autorole remove @role
    !autorole list [page]

    !reactionrole add <message_id> <emoji> @role
    !reactionrole remove <mapping_id>
    !reactionrole list [page] [@role] [#channel]
"""
from __future__ import annotations

import logging
import re

from bot.commands import Bot, Context
from bot.modules.moderation import parse_channel_id
from bot.permissions import PERM_MANAGE_GUILD, role_is_privileged
from common import db

log = logging.getLogger("fluxbot.roles")

ROLE_MENTION_RE = re.compile(r"^<@&(\d+)>$")

AUTOROLE_PAGE_SIZE = 20
REACTION_ROLE_PAGE_SIZE = 10


def parse_role_id(token: str) -> str | None:
    m = ROLE_MENTION_RE.match(token)
    if m:
        return m.group(1)
    if token.isdigit():
        return token
    return None


def register(bot: Bot) -> None:

    # ------------------------------------------------------------ setup --
    @bot.command("autorole", category="Roles", help_text="Manage roles auto-assigned to new members. "
                                        "Usage: !autorole add|remove|list [@role] [page]",
                 required_permission=PERM_MANAGE_GUILD)
    async def autorole(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Usage: `!autorole add @role` / `remove @role` / `list [page]`")
            return
        sub = ctx.args[0].lower()
        if sub == "list":
            role_ids = await db.list_autoroles(ctx.guild_id)
            if not role_ids:
                await ctx.reply("No autoroles configured.")
                return
            page = 1
            for tok in ctx.args[1:]:
                if tok.isdigit():
                    page = max(1, int(tok))
            total_pages = max(1, (len(role_ids) + AUTOROLE_PAGE_SIZE - 1) // AUTOROLE_PAGE_SIZE)
            page = min(page, total_pages)
            start = (page - 1) * AUTOROLE_PAGE_SIZE
            page_ids = role_ids[start:start + AUTOROLE_PAGE_SIZE]
            footer = f"Page {page}/{total_pages}, {len(role_ids)} total."
            if page < total_pages:
                footer += f" See more with `!autorole list {page + 1}`."
            await ctx.reply("Autoroles: " + ", ".join(f"<@&{r}>" for r in page_ids) + f"\n\n_{footer}_")
            return
        if len(ctx.args) < 2:
            await ctx.reply(f"Usage: `!autorole {sub} @role`")
            return
        role_id = parse_role_id(ctx.args[1])
        if not role_id:
            await ctx.reply(f"Couldn't parse `{ctx.args[1]}` as a role.")
            return
        if sub == "add":
            try:
                guild = await ctx.bot.get_guild(ctx.guild_id, fresh=True)
            except Exception:
                await ctx.reply("Couldn't verify that role right now, try again in a moment.")
                return
            if role_is_privileged(guild, role_id):
                await ctx.reply("🚫 That role carries moderation/admin permissions, autoroles can't grant it "
                                 "automatically to every new member. Assign it manually instead.")
                return
            await db.add_autorole(ctx.guild_id, role_id)
            await ctx.reply(f"✅ New members will now get <@&{role_id}>.")
        elif sub == "remove":
            await db.remove_autorole(ctx.guild_id, role_id)
            await ctx.reply(f"✅ Removed <@&{role_id}> from autoroles.")
        else:
            await ctx.reply("Usage: `!autorole add @role` / `remove @role` / `list`")

    @bot.command("reactionrole", category="Roles", aliases=["rr"], required_permission=PERM_MANAGE_GUILD,
                 help_text="Map a reaction to a role. "
                            "Usage: !reactionrole add <message_id> <emoji> @role")
    async def reactionrole(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Usage: `!reactionrole add <message_id> <emoji> @role` / "
                             "`remove <mapping_id>` / `list [page] [@role] [#channel]`")
            return
        sub = ctx.args[0].lower()
        if sub == "list":
            rows = await db.list_reaction_roles(ctx.guild_id)
            if not rows:
                await ctx.reply("No reaction roles configured.")
                return

            page = 1
            filter_role_id = None
            filter_channel_id = None
            for tok in ctx.args[1:]:
                if tok.startswith("<@&"):
                    filter_role_id = parse_role_id(tok) or filter_role_id
                elif tok.startswith("<#"):
                    filter_channel_id = parse_channel_id(tok) or filter_channel_id
                elif tok.isdigit():
                    page = max(1, int(tok))

            if filter_role_id:
                rows = [r for r in rows if r["role_id"] == filter_role_id]
            if filter_channel_id:
                rows = [r for r in rows if r["channel_id"] == filter_channel_id]
            if not rows:
                await ctx.reply("No reaction roles match that filter.")
                return

            total_pages = max(1, (len(rows) + REACTION_ROLE_PAGE_SIZE - 1) // REACTION_ROLE_PAGE_SIZE)
            page = min(page, total_pages)
            start = (page - 1) * REACTION_ROLE_PAGE_SIZE
            page_rows = rows[start:start + REACTION_ROLE_PAGE_SIZE]
            lines = [f"`#{r['id']}` {r['emoji']} to <@&{r['role_id']}> "
                     f"(message `{r['message_id']}` in <#{r['channel_id']}>)" for r in page_rows]
            footer = f"Page {page}/{total_pages}, {len(rows)} total."
            if page < total_pages:
                footer += f" See more with `!reactionrole list {page + 1}`."
            await ctx.embed("Reaction roles", "\n".join(lines) + f"\n\n_{footer}_")
            return
        if sub == "remove":
            if len(ctx.args) < 2 or not ctx.args[1].isdigit():
                await ctx.reply("Usage: `!reactionrole remove <mapping_id>` (see `!reactionrole list`)")
                return
            await db.remove_reaction_role(ctx.guild_id, int(ctx.args[1]))
            await ctx.reply("✅ Removed that reaction role mapping.")
            return
        if sub == "add":
            if len(ctx.args) < 4:
                await ctx.reply("Usage: `!reactionrole add <message_id> <emoji> @role`")
                return
            message_id, emoji = ctx.args[1], ctx.args[2]
            role_id = parse_role_id(ctx.args[3])
            if not role_id:
                await ctx.reply(f"Couldn't parse `{ctx.args[3]}` as a role.")
                return
            try:
                guild = await ctx.bot.get_guild(ctx.guild_id, fresh=True)
            except Exception:
                await ctx.reply("Couldn't verify that role right now, try again in a moment.")
                return
            if role_is_privileged(guild, role_id):
                await ctx.reply("🚫 That role carries moderation/admin permissions, reaction roles can't "
                                 "hand it out to anyone who clicks. Assign it manually instead.")
                return
            try:
                await ctx.bot.rest.get_message(ctx.channel_id, message_id)
            except Exception:
                await ctx.reply(f"Couldn't find message `{message_id}` in this channel. Run this command in "
                                 f"the same channel as the message you want to react to.")
                return
            await db.add_reaction_role(ctx.guild_id, ctx.channel_id, message_id, emoji, role_id)
            try:
                await ctx.bot.rest.add_reaction(ctx.channel_id, message_id, emoji)
            except Exception:
                pass  # message may be in another channel or emoji format may need adjusting for your instance
            await ctx.reply(f"✅ Reacting {emoji} on message `{message_id}` now grants <@&{role_id}>.")
            return
        await ctx.reply("Usage: `!reactionrole add <message_id> <emoji> @role` / "
                         "`remove <mapping_id>` / `list`")

    # ---------------------------------------------------------- listeners --
    @bot.on("GUILD_MEMBER_ADD")
    async def on_member_add(data: dict) -> None:
        guild_id = data.get("guild_id")
        user = data.get("user", {})
        user_id = user.get("id")
        if not guild_id or not user_id:
            log.warning("GUILD_MEMBER_ADD missing guild_id/user, can't apply autoroles: %r", data)
            return
        guild_id = str(guild_id)
        role_ids = await db.list_autoroles(guild_id)
        for role_id in role_ids:
            try:
                await bot.rest.add_member_role(guild_id, str(user_id), role_id)
            except Exception:
                log.warning("Couldn't add autorole %s to %s in guild %s",
                            role_id, user_id, guild_id, exc_info=True)

        guild_cfg = await db.get_guild(guild_id)
        if guild_cfg and guild_cfg["welcome_channel_id"] and guild_cfg["welcome_message"]:
            try:
                guild = await bot.get_guild(guild_id)
            except Exception:
                guild = {}
            text = (guild_cfg["welcome_message"]
                    .replace("{user}", f"<@{user_id}>")
                    .replace("{username}", user.get("username", "there"))
                    .replace("{server}", guild.get("name", "the server"))
                    .replace("{membercount}", str(guild.get("member_count", ""))))
            try:
                await bot.rest.send_message(guild_cfg["welcome_channel_id"], content=text,
                                             allowed_mentions=bot.rest.mention_only(user_id))
            except Exception:
                pass

    @bot.on("GUILD_MEMBER_REMOVE")
    async def on_member_remove(data: dict) -> None:
        guild_id = str(data.get("guild_id"))
        user = data.get("user", {})
        user_id = user.get("id")
        if not user_id:
            return
        guild_cfg = await db.get_guild(guild_id)
        if not (guild_cfg and guild_cfg["goodbye_channel_id"] and guild_cfg["goodbye_message"]):
            return
        try:
            guild = await bot.get_guild(guild_id)
        except Exception:
            guild = {}
        # No {user} mention here on purpose, the member has already left, so
        # a mention would just render as an unresolved/greyed-out user.
        text = (guild_cfg["goodbye_message"]
                .replace("{user}", user.get("username", "Someone"))
                .replace("{username}", user.get("username", "Someone"))
                .replace("{server}", guild.get("name", "the server"))
                .replace("{membercount}", str(guild.get("member_count", ""))))
        try:
            await bot.rest.send_message(guild_cfg["goodbye_channel_id"], content=text)
        except Exception:
            pass

    @bot.on("MESSAGE_REACTION_ADD")
    async def on_reaction_add(data: dict) -> None:
        message_id = str(data.get("message_id"))
        emoji_data = data.get("emoji", {})
        emoji = emoji_data.get("name") if isinstance(emoji_data, dict) else emoji_data
        user_id = data.get("user_id")
        guild_id = data.get("guild_id")
        if not (message_id and emoji and user_id and guild_id):
            return
        bot_user_id = (bot.gateway.user or {}).get("id")
        if bot_user_id and str(user_id) == str(bot_user_id):
            return  # our own seed reaction when the mapping was created, not a real member reacting
        mapping = await db.get_reaction_role(str(guild_id), message_id, str(emoji))
        if not mapping:
            return
        try:
            await bot.rest.add_member_role(str(guild_id), str(user_id), mapping["role_id"])
        except Exception:
            pass

    @bot.on("MESSAGE_REACTION_REMOVE")
    async def on_reaction_remove(data: dict) -> None:
        message_id = str(data.get("message_id"))
        emoji_data = data.get("emoji", {})
        emoji = emoji_data.get("name") if isinstance(emoji_data, dict) else emoji_data
        user_id = data.get("user_id")
        guild_id = data.get("guild_id")
        if not (message_id and emoji and user_id and guild_id):
            return
        bot_user_id = (bot.gateway.user or {}).get("id")
        if bot_user_id and str(user_id) == str(bot_user_id):
            return  # not a real member's reaction
        mapping = await db.get_reaction_role(str(guild_id), message_id, str(emoji))
        if not mapping:
            return
        try:
            await bot.rest.remove_member_role(str(guild_id), str(user_id), mapping["role_id"])
        except Exception:
            pass
