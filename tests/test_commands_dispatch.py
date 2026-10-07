"""Dispatch-level tests for bot/commands.py's Bot._on_message.

Registers throwaway test commands directly (rather than importing a real
feature module) so these stay focused on the dispatch machinery itself
(prefix resolution, permission gating, tag fallback) and don't drift
every time a command module's own behavior changes.
"""
from __future__ import annotations

from bot.commands import Bot, Context
from bot.permissions import PERM_BAN_MEMBERS
from common import db


def make_bot():
    bot = Bot("test-token")

    @bot.command("echo", category="Test", help_text="echo back the args")
    async def echo(ctx: Context) -> None:
        await ctx.reply(" ".join(ctx.args) or "(nothing)")

    @bot.command("modsonly", category="Test", required_permission=PERM_BAN_MEMBERS)
    async def modsonly(ctx: Context) -> None:
        await ctx.reply("you're a mod")

    return bot


async def stub_rest(bot, guild_roles=None, member_roles=None, owner_id="owner1"):
    """Replaces the REST calls _on_message needs with in-memory fakes, no
    real HTTP. Returns the list of message contents sent via ctx.reply()."""
    sent = []

    async def fake_send_message(channel_id, content=None, embeds=None, **kw):
        sent.append(content)
        return {"id": "1"}

    async def fake_get_guild(guild_id):
        return {"id": guild_id, "owner_id": owner_id, "roles": guild_roles or []}

    async def fake_get_member(guild_id, user_id):
        return {"user": {"id": user_id}, "roles": member_roles or []}

    bot.rest.send_message = fake_send_message
    bot.rest.get_guild = fake_get_guild
    bot.rest.get_guild_member = fake_get_member
    return sent


def message(content, guild_id, author_id="u1"):
    return {
        "content": content, "author": {"id": author_id, "username": "tester"},
        "guild_id": guild_id, "channel_id": "chan1",
    }


async def test_dispatch_runs_a_registered_command(guild_id):
    bot = make_bot()
    sent = await stub_rest(bot)
    await bot._on_message(message("!echo hello world", guild_id))
    assert sent == ["hello world"]


async def test_dispatch_respects_per_guild_prefix(guild_id):
    await db.update_guild_settings(guild_id, command_prefix="?")
    bot = make_bot()
    sent = await stub_rest(bot)
    await bot._on_message(message("!echo should not run", guild_id))
    assert sent == []
    await bot._on_message(message("?echo should run", guild_id))
    assert sent == ["should run"]


async def test_dispatch_blocks_without_required_permission(guild_id):
    bot = make_bot()
    sent = await stub_rest(bot, owner_id="someone-else")
    await bot._on_message(message("!modsonly", guild_id))
    assert sent == ["You don't have permission to use that command."]


async def test_dispatch_allows_with_required_permission(guild_id):
    bot = make_bot()
    role = {"id": "r1", "permissions": str(PERM_BAN_MEMBERS)}
    sent = await stub_rest(bot, guild_roles=[role], member_roles=["r1"], owner_id="someone-else")
    await bot._on_message(message("!modsonly", guild_id))
    assert sent == ["you're a mod"]


async def test_dispatch_owner_always_passes_permission_check(guild_id):
    bot = make_bot()
    sent = await stub_rest(bot, owner_id="u1")
    await bot._on_message(message("!modsonly", guild_id, author_id="u1"))
    assert sent == ["you're a mod"]


async def test_dispatch_falls_back_to_a_tag(guild_id):
    bot = make_bot()
    sent = await stub_rest(bot)
    await db.add_tag(guild_id, "rules", "Be nice.")
    await bot._on_message(message("!rules", guild_id))
    assert sent == ["Be nice."]


async def test_dispatch_ignores_messages_from_bots(guild_id):
    bot = make_bot()
    sent = await stub_rest(bot)
    data = message("!echo hi", guild_id)
    data["author"]["bot"] = True
    await bot._on_message(data)
    assert sent == []


async def test_dispatch_ignores_dms(guild_id):
    bot = make_bot()
    sent = await stub_rest(bot)
    data = message("!echo hi", guild_id)
    data["guild_id"] = None
    await bot._on_message(data)
    assert sent == []


async def test_dispatch_ignores_unknown_command_with_no_matching_tag(guild_id):
    bot = make_bot()
    sent = await stub_rest(bot)
    await bot._on_message(message("!doesnotexist", guild_id))
    assert sent == []
