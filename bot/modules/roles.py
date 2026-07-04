"""Autorole + reaction roles.

    !autorole add @role       — role auto-assigned to every new member
    !autorole remove @role
    !autorole list

    !reactionrole add <message_id> <emoji> @role
    !reactionrole remove <mapping_id>
    !reactionrole list
"""
from __future__ import annotations

import re

from bot.commands import Bot, Context
from bot.permissions import PERM_MANAGE_GUILD
from common import db

ROLE_MENTION_RE = re.compile(r"^<@&(\d+)>$")


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
                                        "Usage: !autorole add|remove|list [@role]",
                 required_permission=PERM_MANAGE_GUILD)
    async def autorole(ctx: Context) -> None:
        if not ctx.args:
            await ctx.reply("Usage: `!autorole add @role` / `remove @role` / `list`")
            return
        sub = ctx.args[0].lower()
        if sub == "list":
            role_ids = await db.list_autoroles(ctx.guild_id)
            if not role_ids:
                await ctx.reply("No autoroles configured.")
                return
            await ctx.reply("Autoroles: " + ", ".join(f"<@&{r}>" for r in role_ids))
            return
        if len(ctx.args) < 2:
            await ctx.reply(f"Usage: `!autorole {sub} @role`")
            return
        role_id = parse_role_id(ctx.args[1])
        if not role_id:
            await ctx.reply(f"Couldn't parse `{ctx.args[1]}` as a role.")
            return
        if sub == "add":
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
                             "`remove <mapping_id>` / `list`")
            return
        sub = ctx.args[0].lower()
        if sub == "list":
            rows = await db.list_reaction_roles(ctx.guild_id)
            if not rows:
                await ctx.reply("No reaction roles configured.")
                return
            lines = [f"`#{r['id']}` {r['emoji']} → <@&{r['role_id']}> "
                     f"(message `{r['message_id']}` in <#{r['channel_id']}>)" for r in rows]
            await ctx.embed("Reaction roles", "\n".join(lines))
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
        guild_id = str(data.get("guild_id"))
        user = data.get("user", {})
        user_id = user.get("id")
        if not user_id:
            return
        role_ids = await db.list_autoroles(guild_id)
        for role_id in role_ids:
            try:
                await bot.rest.add_member_role(guild_id, str(user_id), role_id)
            except Exception:
                pass

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
        mapping = await db.get_reaction_role(message_id, str(emoji))
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
        mapping = await db.get_reaction_role(message_id, str(emoji))
        if not mapping:
            return
        try:
            await bot.rest.remove_member_role(str(guild_id), str(user_id), mapping["role_id"])
        except Exception:
            pass
